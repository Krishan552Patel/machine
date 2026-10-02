# ---------------------------------------------------------------------------
# live_bridge.py  —  Client for fab-card-id's persistent identify service +
#                    camera frame sources for live sorting.
#
# The service (fab-card-id/ident_service.py) runs as a long-lived subprocess
# speaking JSON-lines over stdin/stdout: indexes load once per session, then
# each identify costs only its matching time (~150 ms pHash / ~1.4 s ORB).
# Subprocess isolation is required — both repos have a flat config.py.
# ---------------------------------------------------------------------------
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

_FAB_ID_DIR = Path(__file__).resolve().parent.parent / "fab-card-id"
_FAB_PY = _FAB_ID_DIR / ".venv" / "Scripts" / "python.exe"


class IdentClient:
    """Spawn and talk to ident_service.py.  Not thread-safe — one caller."""

    def __init__(self):
        py = str(_FAB_PY) if _FAB_PY.exists() else sys.executable
        self._proc = subprocess.Popen(
            [py, "-u", str(_FAB_ID_DIR / "ident_service.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
            cwd=str(_FAB_ID_DIR),
        )
        self.game: str | None = None

    def _rpc(self, req: dict) -> dict:
        if self._proc.poll() is not None:
            return {"ok": False, "error": "identify service exited"}
        self._proc.stdin.write(json.dumps(req) + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        if not line:
            return {"ok": False, "error": "identify service closed stdout"}
        return json.loads(line)

    def init(self, game: str, mode: str = "auto",
             fixed_orientation: bool = False) -> dict:
        resp = self._rpc({"cmd": "init", "game": game, "mode": mode,
                          "fixed_orientation": fixed_orientation})
        if resp.get("ok"):
            self.game = game
        return resp

    def identify_file(self, path: str, detect: bool = True) -> dict:
        return self._rpc({"cmd": "identify_file", "path": path, "detect": detect})

    def identify_jpeg(self, jpeg_b64: str, detect: bool = True) -> dict:
        return self._rpc({"cmd": "identify_b64", "jpeg_b64": jpeg_b64,
                          "detect": detect})

    def close(self) -> None:
        try:
            self._rpc({"cmd": "shutdown"})
        except Exception:
            pass
        try:
            self._proc.wait(timeout=5)
        except Exception:
            self._proc.kill()


class PhoneCamera:
    """IP Webcam snapshot source (one /shot.jpg per frame — cool phone)."""

    def __init__(self, ip: str, port: int = 8080):
        self.url = f"http://{ip}:{port}/shot.jpg"

    def read_jpeg(self, timeout: float = 8.0) -> bytes | None:
        try:
            with urllib.request.urlopen(self.url, timeout=timeout) as r:
                return r.read()
        except Exception:
            return None


class FolderCamera:
    """Replay a folder of images as if they were camera captures."""

    EXTS = {".jpg", ".jpeg", ".png", ".webp"}

    def __init__(self, folder: str):
        self.files = sorted(p for p in Path(folder).iterdir()
                            if p.suffix.lower() in self.EXTS)
        self._i = 0

    def next_path(self) -> str | None:
        if self._i >= len(self.files):
            return None
        p = self.files[self._i]
        self._i += 1
        return str(p)

    def remaining(self) -> int:
        return len(self.files) - self._i


def card_data_from_result(res: dict):
    """Map an identify-service result to a machine CardData."""
    from card import CardData
    conf_map = {"high": 0.95, "medium": 0.60, "low": 0.45,
                "none": 0.0, "foreign": 0.0}
    conf_str = res.get("confidence", "none")
    return CardData(
        card_id=res.get("key", "") or "unknown",
        name=res.get("name", "") or "Unknown",
        set_code=(res.get("set", "") or "???").upper(),
        rarity=res.get("rarity", ""),
        hero_class=res.get("type_line", "") or "generic",
        price_usd=0.0,
        confidence=conf_map.get(conf_str, 0.0),
        raw_cnn_output={
            "confidence_str": conf_str,
            "method": res.get("method", ""),
            "detail": res.get("detail", ""),
            "type_line": res.get("type_line", ""),
            "rarity": res.get("rarity", ""),
            "game": res.get("game", ""),
            "ms": res.get("ms", 0),
            "candidates": res.get("candidates", []),
            "price": res.get("price"),
        },
    )
