# ---------------------------------------------------------------------------
# ui_server.py  —  Browser control panel for live multi-game card sorting.
#
#   python ui_server.py            (then open http://127.0.0.1:8765)
#
# One page shows the whole pipeline in real time: the camera crop next to
# the matched reference image (with method / confidence / timing), the sort
# decision and its reason, and an animated grid + gantry view.  Identification
# runs in fab-card-id's persistent service (loads once, ~150 ms - 1.4 s per
# card); the gantry is the existing machine simulation.
#
# Sources:  phone (IP Webcam snapshots)  or  folder (replay images).
# Stdlib only — no FastAPI/websockets; live updates go over Server-Sent
# Events, controls over plain POST.
# ---------------------------------------------------------------------------
from __future__ import annotations

import base64
import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import config
from gantry import CoreXYKinematics, Gantry
from grid import CardGrid
from live_bridge import (FolderCamera, IdentClient, PhoneCamera,
                         card_data_from_result)
from motor import StepperMotor
from sorter import MultiGameSorter


def build_gantry() -> Gantry:
    # Same wiring as main.build_gantry, inlined so this server never pulls
    # in main.py's matplotlib-backed visualizer import chain.
    def motor(name, feed, accel):
        return StepperMotor(name, steps_per_mm=config.STEPS_PER_MM,
                            microsteps=config.MICROSTEPS,
                            max_feedrate_mm_s=feed, acceleration_mm_s2=accel)
    return Gantry(
        motor("A", config.MAX_FEEDRATE_MM_S, config.ACCELERATION_MM_S2),
        motor("B", config.MAX_FEEDRATE_MM_S, config.ACCELERATION_MM_S2),
        motor("Z", config.Z_SPEED_MM_S, config.Z_ACCELERATION_MM_S2),
        CoreXYKinematics(),
    )

STATIC_DIR = Path(__file__).parent / "static"
PORT = 8765

# After placing a card, the same key is not accepted again until the camera
# has seen at least one no-card/no-match frame (the operator swapped cards).
_REPEAT_RESET_S = 20.0


class SortSession(threading.Thread):
    """One sorting run: camera -> identify -> sort -> gantry -> events."""

    def __init__(self, cfg: dict, bus: "EventBus"):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.bus = bus
        self.stop_flag = threading.Event()
        self.pause_flag = threading.Event()
        self.game = cfg.get("game", "riftbound")
        self.mode = cfg.get("mode", "rarity")
        rows, cols = int(cfg.get("rows", 6)), int(cfg.get("cols", 4))
        self.grid = CardGrid(rows=rows, cols=cols)
        self.gantry = build_gantry()
        self.sorter = MultiGameSorter(self.game, self.mode)
        self.svc: IdentClient | None = None
        self.stats = {"sorted": 0, "review": 0, "other_game": 0,
                      "no_match_frames": 0, "frames": 0, "started": time.time()}
        self.allowed_refs: set[str] = set()

    # ── event helpers ────────────────────────────────────────────────────
    def emit(self, type_: str, **data):
        self.bus.publish({"type": type_, **data})

    def emit_grid(self):
        cells = []
        for row in self.grid.get_grid_snapshot():
            for cell in row:
                cells.append({
                    "r": cell.row, "c": cell.col, "n": len(cell.cards),
                    "names": [c.name for c in cell.cards[-3:]],
                    "rarity": cell.cards[-1].rarity if cell.cards else "",
                })
        review = (min(config.NEEDS_REVIEW_CELL[0], self.grid.rows - 1),
                  min(config.NEEDS_REVIEW_CELL[1], self.grid.cols - 1))
        other = (min(config.OTHER_GAME_CELL[0], self.grid.rows - 1),
                 min(config.OTHER_GAME_CELL[1], self.grid.cols - 1))
        self.emit("grid", rows=self.grid.rows, cols=self.grid.cols,
                  cells=cells, review_cell=review, other_cell=other)

    def emit_stats(self):
        s = dict(self.stats)
        mins = max((time.time() - s.pop("started")) / 60.0, 1e-6)
        s["cards_per_hour"] = round(60.0 * s["sorted"] / mins)
        s["sim_time_s"] = round(self.gantry.get_simulated_time(), 1)
        s["travel_mm"] = round(self.gantry.get_total_distance())
        self.emit("stats", **s)

    # ── main loop ────────────────────────────────────────────────────────
    def run(self):
        tiers = (config.MULTIGAME_RARITY_TIERS if self.mode == "rarity"
                 else config.MULTIGAME_TYPE_ORDERS).get(self.game, [])
        self.emit("session", state="loading", game=self.game, mode=self.mode,
                  tiers=tiers)
        self.svc = IdentClient()
        resp = self.svc.init(self.game, mode=self.cfg.get("accuracy", "auto"),
                             fixed_orientation=bool(self.cfg.get("fixed_orientation")))
        if not resp.get("ok"):
            self.emit("session", state="error",
                      error=f"identify service failed: {resp.get('error')}")
            return
        src = self.cfg.get("source", "folder")
        phone = folder = None
        if src == "phone":
            phone = PhoneCamera(self.cfg.get("ip", ""), int(self.cfg.get("port", 8080)))
        else:
            try:
                folder = FolderCamera(self.cfg.get("folder", ""))
            except Exception as e:
                self.emit("session", state="error", error=f"bad folder: {e}")
                return
        self.gantry.home()
        self.emit("session", state="running", game=self.game, mode=self.mode,
                  tiers=tiers)
        self.emit_grid()

        last_key, last_key_at, saw_gap = None, 0.0, True
        unknown_streak, unknown_armed = 0, True
        while not self.stop_flag.is_set():
            if self.pause_flag.is_set():
                time.sleep(0.2)
                continue
            self.stats["frames"] += 1
            # ── acquire + identify ───────────────────────────────────────
            if phone:
                jpeg = phone.read_jpeg()
                if jpeg is None:
                    self.emit("status", msg="camera unreachable — retrying")
                    time.sleep(2.0)
                    continue
                res = self.svc.identify_jpeg(
                    base64.b64encode(jpeg).decode(), detect=True)
            else:
                path = folder.next_path()
                if path is None:
                    self.emit("status", msg="folder finished")
                    break
                res = self.svc.identify_file(path, detect=True)

            if not res.get("ok"):
                self.emit("status", msg=f"identify error: {res.get('error')}")
                continue
            if res.get("ref_image"):
                self.allowed_refs.add(res["ref_image"])
            self.emit("identify", **{k: res.get(k, "") for k in (
                "found", "key", "name", "set", "collector", "rarity",
                "type_line", "method", "confidence", "detail", "ms",
                "crop_b64", "ref_image", "crop_how")})

            # ── game gate ───────────────────────────────────────────────
            # 1. identified in the selected game        -> sort by tier
            # 2. positively another game's card         -> wrong-game box
            # 3. a card is in view but nothing matched  -> review pile
            # 4. no card in view at all                 -> skip (gap)
            is_foreign = res.get("confidence") == "foreign"
            if not res.get("found") and not is_foreign:
                card_seen = res.get("crop_how") in ("edge", "solid", "precropped")
                if phone and not card_seen:
                    self.stats["no_match_frames"] += 1
                    saw_gap, unknown_streak, unknown_armed = True, 0, True
                    self.emit("status", msg="no card in view")
                    self.emit_stats()
                    continue
                if phone:
                    # A card is under the camera but nothing matched.  Ask for
                    # a second consecutive look before committing to review,
                    # and only place ONE unknown until the view clears —
                    # otherwise a parked mystery card floods the review cell.
                    unknown_streak += 1
                    if unknown_streak < 2 or not unknown_armed:
                        self.emit("status",
                                  msg="unrecognized card — confirming...")
                        continue
                    unknown_armed = False
                from card import CardData
                card = CardData(
                    card_id="unknown", name="Unknown card", set_code="???",
                    rarity="", hero_class="", confidence=0.0,
                    raw_cnn_output={"confidence_str": res.get("confidence",
                                                              "none")})
                self._place(card, res, reason_override="unidentifiable -> review")
                last_key, saw_gap, unknown_streak = None, False, 0
                continue
            unknown_streak = 0

            # ── repeat guard (live camera: same card still in view) ─────
            key = res.get("key", "")
            if phone and key == last_key and not saw_gap \
                    and time.time() - last_key_at < _REPEAT_RESET_S:
                self.emit("status", msg=f"{res.get('name')} already placed — "
                          "swap to the next card")
                continue

            # ── sort + simulate the pick/place ──────────────────────────
            card = card_data_from_result(res)
            if is_foreign:
                card.name = (f"{card.name} [{res['foreign_game']}]"
                             if res.get("foreign_game") else "Other-game card")
            self._place(card, res)
            last_key, last_key_at = key, time.time()
            saw_gap, unknown_armed = False, True
        self.svc.close()
        self.emit("session", state="stopped")

    def _place(self, card, res: dict, reason_override: str = "") -> None:
        """Assign a cell, run the simulated pick/place, update grid + stats."""
        cell = self.sorter.assign_cell(card, self.grid)
        reason = reason_override or self.sorter.describe(card, cell)
        tx, ty = self.grid.get_cell_position(*cell)
        sx, sy = config.STACK_X_MM, config.STACK_Y_MM
        moves = []
        for x, y in ((sx, sy), (tx, ty)):
            rec = self.gantry.move_xy(x, y)
            self.gantry.move_z(config.Z_TRAVEL_MM)
            self.gantry.move_z(0.0)
            moves.append({"x": x, "y": y, "dur": round(rec.duration_s, 3)})
        self.grid.place_card(*cell, card)

        # Count by the sort decision (a low-confidence card whose rarity/type
        # is still certain lands in a tier, not review).
        kind = (self.sorter.placement_kind(card)
                if hasattr(self.sorter, "placement_kind") else "sorted")
        self.stats[{"other": "other_game", "review": "review"}.get(kind, "sorted")] += 1
        self.emit("sort", key=res.get("key", ""), name=card.name,
                  cell=list(cell), reason=reason, moves=moves,
                  rarity=card.rarity, type_line=res.get("type_line", ""))
        self.emit_grid()
        self.emit_stats()

    def stop(self):
        self.stop_flag.set()


class EventBus:
    """Fan-out queue: every SSE client gets every event; late joiners get
    the last session/grid/stats snapshot so the page can rebuild."""

    def __init__(self):
        self._clients: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._last: dict[str, dict] = {}

    def publish(self, event: dict):
        with self._lock:
            if event.get("type") in ("session", "grid", "stats"):
                self._last[event["type"]] = event
            for q in list(self._clients):
                q.put(event)

    def subscribe(self) -> queue.Queue:
        q = queue.Queue(maxsize=500)
        with self._lock:
            for ev in self._last.values():
                q.put(ev)
            self._clients.append(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)


BUS = EventBus()
SESSION: SortSession | None = None
SESSION_LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):            # quiet console
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            body = (STATIC_DIR / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif url.path == "/api/status":
            # Backend readiness per game — spawns a throwaway client that only
            # reads the filesystem (no index load), then exits.
            try:
                c = IdentClient()
                st = c._rpc({"cmd": "status"})
                c.close()
            except Exception as e:
                st = {"ok": False, "error": str(e)}
            self._json(st)
        elif url.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            q = BUS.subscribe()
            try:
                while True:
                    try:
                        ev = q.get(timeout=15)
                        self.wfile.write(
                            f"data: {json.dumps(ev)}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionError, OSError):
                pass
            finally:
                BUS.unsubscribe(q)
        elif url.path == "/ref":
            # Reference images: only paths the identify service reported.
            p = parse_qs(url.query).get("p", [""])[0]
            sess = SESSION
            if sess and p in sess.allowed_refs and Path(p).exists():
                body = Path(p).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def do_POST(self):
        global SESSION
        n = int(self.headers.get("Content-Length", 0))
        cfg = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/api/start":
            with SESSION_LOCK:
                if SESSION and SESSION.is_alive():
                    SESSION.stop()
                    SESSION.join(timeout=10)
                SESSION = SortSession(cfg, BUS)
                SESSION.start()
            self._json({"ok": True})
        elif self.path == "/api/stop":
            with SESSION_LOCK:
                if SESSION:
                    SESSION.stop()
            self._json({"ok": True})
        elif self.path == "/api/pause":
            if SESSION:
                if cfg.get("paused"):
                    SESSION.pause_flag.set()
                else:
                    SESSION.pause_flag.clear()
            self._json({"ok": True})
        elif self.path == "/api/test_identify":
            # One-off identify for testing/calibration — reuses a cached
            # client, re-initialising only when the game/mode changes.
            self._json(test_identify(cfg))
        else:
            self.send_error(404)


# ── Single-card test identify (cached client) ─────────────────────────────────
_TEST = {"client": None, "game": None, "mode": None}
_TEST_LOCK = threading.Lock()


def test_identify(cfg: dict) -> dict:
    game = cfg.get("game", "riftbound")
    mode = cfg.get("accuracy", "auto")
    jpeg_b64 = cfg.get("jpeg_b64", "")
    if not jpeg_b64:
        return {"ok": False, "error": "no image"}
    with _TEST_LOCK:
        if (_TEST["client"] is None or _TEST["game"] != game
                or _TEST["mode"] != mode):
            if _TEST["client"]:
                _TEST["client"].close()
            _TEST["client"] = IdentClient()
            r = _TEST["client"].init(game, mode=mode)
            if not r.get("ok"):
                return r
            _TEST["game"], _TEST["mode"] = game, mode
        t0 = time.time()
        res = _TEST["client"].identify_jpeg(jpeg_b64, detect=bool(cfg.get("detect", True)))
        res["client_ms"] = round((time.time() - t0) * 1000)
        return res


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Card sorter UI: http://127.0.0.1:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
