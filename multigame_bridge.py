# ---------------------------------------------------------------------------
# multigame_bridge.py  —  Scan a folder of Magic (or other game) card images
#                         with fab-card-id's multigame OCR ladder and build an
#                         InputStack ready for the machine sorter.
#
# Usage:
#   from multigame_bridge import scan_folder_to_stack, MultiGameSetSorter
#   stack = scan_folder_to_stack("E:/CARDDATA/magic/bench")
#
# Headless simulator smoke test:
#   python multigame_bridge.py [images_dir]
# ---------------------------------------------------------------------------
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import config as machine_config  # machine/config.py

# Identification runs in a SUBPROCESS (fab-card-id/multigame_scan.py) rather
# than in-process: both repos have a flat config.py, so putting fab-card-id
# on sys.path here would shadow machine's own config import.
_FAB_ID_DIR = Path(__file__).resolve().parent.parent / "fab-card-id"

# Map multigame confidence strings -> float scores for CardData.
# Only "high" (capture-store hit, or index-validated + name-vetoed collector
# OCR) clears machine_config.CNN_CONFIDENCE_THRESHOLD (0.75); everything else
# routes to the NEEDS_REVIEW cell.
_CONFIDENCE_MAP: dict[str, float] = {
    "high":   0.95,
    "medium": 0.60,
    "low":    0.45,
    "none":   0.0,
}


def scan_folder_to_stack(images_dir: str, game: str = "magic"):
    """
    Identify every card image in a folder with the multigame ladder (run in a
    fab-card-id subprocess) and return an InputStack for machine simulation.
    """
    from card import CardData, InputStack          # machine/card.py

    print(f"[MultiGameBridge] Scanning {images_dir} via multigame_scan.py ({game})...")
    proc = subprocess.run(
        [sys.executable, str(_FAB_ID_DIR / "multigame_scan.py"), str(images_dir),
         "--game", game],
        capture_output=True, text=True, encoding="utf-8", cwd=str(_FAB_ID_DIR),
    )
    if proc.returncode != 0:
        print(f"[MultiGameBridge] scan failed:\n{proc.stderr}")
        return InputStack()
    rows = json.loads(proc.stdout)

    identified: list[CardData] = []
    review_count = 0
    for i, row in enumerate(rows, start=1):
        conf = _CONFIDENCE_MAP.get(row["confidence"], 0.0)
        if conf < machine_config.CNN_CONFIDENCE_THRESHOLD:
            review_count += 1
            status = "-> NEEDS REVIEW"
        else:
            status = f"[{row['set'].upper()}] via {row['method']}"
        print(f"  [{i}/{len(rows)}] {row['file']:<18} "
              f"\"{row['name'] or '???'}\"  {status} (conf={row['confidence']})")

        identified.append(CardData(
            card_id=row["key"] or Path(row["file"]).stem,
            name=row["name"] or "Unknown",
            set_code=(row["set"] or "???").upper(),
            rarity=machine_config.RARITY_COMMON,   # not provided by multigame
            hero_class="generic",
            confidence=conf,
            raw_cnn_output={
                "game": game,
                "method": row["method"],
                "mg_confidence": row["confidence"],
                "n_candidates": row["n_candidates"],
            },
        ))

    print("-" * 65)
    print(f"[MultiGameBridge] {len(identified)} card(s)  |  review: {review_count}  |  "
          f"threshold: {machine_config.CNN_CONFIDENCE_THRESHOLD:.2f}\n")
    stack = InputStack()
    stack.load_from_list(identified)
    return stack


class MultiGameSetSorter:
    """
    Sorter for multi-game cards: each SET gets a column (assigned in encounter
    order, wrapping over the columns left of the review column), cards fill
    the column top-down.  Sub-threshold confidence -> NEEDS_REVIEW cell.
    """

    def __init__(self) -> None:
        self._set_col: dict[str, int] = {}

    def assign_cell(self, card, grid):
        if card.confidence < machine_config.CNN_CONFIDENCE_THRESHOLD:
            r0, c0 = machine_config.NEEDS_REVIEW_CELL
            return min(r0, grid.rows - 1), min(c0, grid.cols - 1)

        n_set_cols = max(1, grid.cols - 1)  # last column reserved for review
        col = self._set_col.setdefault(card.set_code, len(self._set_col) % n_set_cols)
        for r in range(grid.rows):
            if not grid.get_cell(r, col).is_full:
                return r, col
        empty = grid.find_empty_cell()
        if empty:
            return empty.row, empty.col
        r0, c0 = machine_config.NEEDS_REVIEW_CELL
        return min(r0, grid.rows - 1), min(c0, grid.cols - 1)


if __name__ == "__main__":
    from grid import CardGrid
    from main import build_gantry
    from simulation import Simulation

    images_dir = sys.argv[1] if len(sys.argv) > 1 else "E:/CARDDATA/magic/bench"
    game = sys.argv[2] if len(sys.argv) > 2 else "magic"
    stack = scan_folder_to_stack(images_dir, game=game)
    if stack.is_empty():
        sys.exit(1)

    sim = Simulation(
        gantry=build_gantry(),
        grid=CardGrid(rows=machine_config.GRID_ROWS, cols=machine_config.GRID_COLS),
        stack=stack,
        sorter=MultiGameSetSorter(),
    )
    sim.run()
