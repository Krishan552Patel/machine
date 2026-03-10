# ---------------------------------------------------------------------------
# sorter.py  —  Sorting strategy protocol + FaB rule-based sorter + CNN stub
# ---------------------------------------------------------------------------
from __future__ import annotations
from typing import Protocol, Any

import config
from card import CardData
from grid import CardGrid


# ---------------------------------------------------------------------------
# Protocol  —  every sorter must implement this single method
# ---------------------------------------------------------------------------

class SortingStrategy(Protocol):
    """
    The CNN integration boundary.

    To plug in a real CNN model, create a class with this one method.
    No imports from this file are required — Python structural typing
    (Protocol) handles duck-typing automatically.
    """

    def assign_cell(self, card: CardData, grid: CardGrid) -> tuple[int, int]:
        """
        Given a card and the current grid state, return the (row, col)
        destination cell.

        The grid must NOT be modified inside this method — it is passed
        read-only by convention.
        """
        ...


# ---------------------------------------------------------------------------
# FaBRuleBasedSorter  —  Flesh and Blood sorting logic without CNN
# ---------------------------------------------------------------------------

# Rarity tiers: lower number = higher priority row
_FAB_RARITY_ROW: dict[str, int] = {
    config.RARITY_FABLED: 0,
    config.RARITY_LEGENDARY: 0,
    config.RARITY_COLD_FOIL: 1,
    config.RARITY_MAJESTIC: 1,
    config.RARITY_SUPER_RARE: 1,
    config.RARITY_RARE: 2,
    config.RARITY_COMMON: 3,
    config.RARITY_TOKEN: 3,
}

# Set code -> column index for by_set / by_rarity_and_set strategies
_FAB_SET_COL: dict[str, int] = {s: i for i, s in enumerate(config.FAB_SETS)}


class FaBRuleBasedSorter:
    """
    Rule-based sorter for Flesh and Blood.

    Strategies (set at construction time):
      "by_rarity"          — row = rarity tier, first available column
      "by_set"             — col = set code, first available row
      "by_price"           — row = price tier ($0-1 / $1-5 / $5-20 / $20+)
      "by_rarity_and_set"  — row = rarity tier, col = set code (most useful)

    If the target cell is full, falls back to the nearest non-full cell
    in the same row, then any empty cell in the grid.
    """

    PRICE_TIERS: list[float] = [1.0, 5.0, 20.0]  # tier boundaries in USD

    def __init__(
        self,
        strategy: str = "by_rarity_and_set",
        fallback_cell: tuple[int, int] = (3, 0),
    ) -> None:
        valid = {"by_rarity", "by_set", "by_price", "by_rarity_and_set"}
        if strategy not in valid:
            raise ValueError(f"Unknown strategy {strategy!r}. Choose from {valid}.")
        self.strategy = strategy
        self.fallback_cell = fallback_cell

    def assign_cell(self, card: CardData, grid: CardGrid) -> tuple[int, int]:
        row, col = self._preferred_cell(card, grid)
        # Clamp to valid grid bounds
        row = min(row, grid.rows - 1)
        col = min(col, grid.cols - 1)
        return self._resolve(row, col, grid)

    # ------------------------------------------------------------------
    # Strategy implementations
    # ------------------------------------------------------------------

    def _preferred_cell(self, card: CardData, grid: CardGrid) -> tuple[int, int]:
        if self.strategy == "by_rarity":
            row = _FAB_RARITY_ROW.get(card.rarity, grid.rows - 1)
            return row, 0

        if self.strategy == "by_set":
            col = _FAB_SET_COL.get(card.set_code, grid.cols - 1)
            return 0, col

        if self.strategy == "by_price":
            row = self._price_row(card.price_usd, grid.rows)
            return row, 0

        if self.strategy == "by_rarity_and_set":
            row = _FAB_RARITY_ROW.get(card.rarity, grid.rows - 1)
            col = _FAB_SET_COL.get(card.set_code, grid.cols - 1)
            return row, col

        return self.fallback_cell

    def _price_row(self, price: float, max_rows: int) -> int:
        for i, threshold in enumerate(self.PRICE_TIERS):
            if price <= threshold:
                return min(i, max_rows - 1)
        return min(len(self.PRICE_TIERS), max_rows - 1)

    # ------------------------------------------------------------------
    # Overflow resolution
    # ------------------------------------------------------------------

    def _resolve(self, preferred_row: int, preferred_col: int, grid: CardGrid) -> tuple[int, int]:
        """
        Try preferred cell -> scan row -> scan whole grid -> fallback.
        """
        # 1. Try exact preferred cell
        cell = grid.get_cell(preferred_row, preferred_col)
        if not cell.is_full:
            return preferred_row, preferred_col

        # 2. Scan the preferred row
        row_cell = self._find_in_row(preferred_row, grid)
        if row_cell:
            return row_cell.row, row_cell.col

        # 3. Scan the preferred column
        col_cell = self._find_in_col(preferred_col, grid)
        if col_cell:
            return col_cell.row, col_cell.col

        # 4. Any empty cell
        any_cell = grid.find_empty_cell()
        if any_cell:
            return any_cell.row, any_cell.col

        # 5. Absolute fallback (will raise CellFullError on placement if also full)
        fb_r = min(self.fallback_cell[0], grid.rows - 1)
        fb_c = min(self.fallback_cell[1], grid.cols - 1)
        return fb_r, fb_c

    def _find_in_row(self, row: int, grid: CardGrid):
        for c in range(grid.cols):
            cell = grid.get_cell(row, c)
            if not cell.is_full:
                return cell
        return None

    def _find_in_col(self, col: int, grid: CardGrid):
        for r in range(grid.rows):
            cell = grid.get_cell(r, col)
            if not cell.is_full:
                return cell
        return None


# ---------------------------------------------------------------------------
# FabIdSorter  —  Driven by fab-card-id sort_bin (pHash + Neon prices)
# ---------------------------------------------------------------------------

# Maps fab-card-id sort bins to preferred grid rows
_BIN_ROW: dict[str, int] = {
    "high_value": 0,
    "mid_value":  1,
    "bulk":       2,
}


class FabIdSorter:
    """
    Sorter driven by the sort_bin assigned by fab-card-id's SortingPipeline.

    Reads card.raw_cnn_output["sort_bin"] (populated by fab_id_bridge) and
    routes cards to grid rows by value tier:

        Row 0  — high_value  (>= $10 CAD)
        Row 1  — mid_value   ($1–$10 CAD)
        Row 2  — bulk        (< $1 CAD or no price)
        NEEDS_REVIEW_CELL — review (low confidence) or unknown (no match)

    Within each row cards fill left to right; overflows to any empty cell.
    Falls back to FaBRuleBasedSorter if no sort_bin is present.
    """

    def __init__(self, fallback_strategy: str = "by_rarity_and_set") -> None:
        self._fallback = FaBRuleBasedSorter(strategy=fallback_strategy)

    def assign_cell(self, card: CardData, grid: CardGrid) -> tuple[int, int]:
        sort_bin = (card.raw_cnn_output or {}).get("sort_bin")

        if sort_bin in ("review", "unknown") or sort_bin is None:
            nr = config.NEEDS_REVIEW_CELL
            return min(nr[0], grid.rows - 1), min(nr[1], grid.cols - 1)

        if sort_bin not in _BIN_ROW:
            return self._fallback.assign_cell(card, grid)

        preferred_row = min(_BIN_ROW[sort_bin], grid.rows - 1)

        # Fill left to right within the preferred row
        for c in range(grid.cols):
            cell = grid.get_cell(preferred_row, c)
            if not cell.is_full:
                return preferred_row, c

        # Row full — any empty cell in the grid
        any_cell = grid.find_empty_cell()
        if any_cell:
            return any_cell.row, any_cell.col

        nr = config.NEEDS_REVIEW_CELL
        return min(nr[0], grid.rows - 1), min(nr[1], grid.cols - 1)


# ---------------------------------------------------------------------------
# CNNSorter  —  Integration stub for the real CNN model
# ---------------------------------------------------------------------------

class CNNSorter:
    """
    Plug-in point for the CNN model.

    Pass in a `label_to_cell_map` that maps CNN output labels to (row, col).
    For any card where the CNN output cannot be mapped, falls back to
    FaBRuleBasedSorter.

    Low-confidence cards (< config.CNN_CONFIDENCE_THRESHOLD) are always
    routed to the NEEDS_REVIEW cell defined in config.

    Usage:
        sorter = CNNSorter(label_to_cell_map={"Dorinthea Ironsong": (0, 0), ...})
        sim.set_sorter(sorter)

    Or with a live hook that calls your model:
        def my_model(card):
            return {"name": "...", "confidence": 0.95, ...}
        sim.set_cnn_hook(my_model)
        # hook writes card.raw_cnn_output before assign_cell is called
    """

    def __init__(
        self,
        label_to_cell_map: dict[str, tuple[int, int]] | None = None,
        fallback_strategy: str = "by_rarity_and_set",
    ) -> None:
        self.label_to_cell_map: dict[str, tuple[int, int]] = label_to_cell_map or {}
        self._fallback = FaBRuleBasedSorter(strategy=fallback_strategy)

    def assign_cell(self, card: CardData, grid: CardGrid) -> tuple[int, int]:
        # Low-confidence -> needs review
        if card.confidence < config.CNN_CONFIDENCE_THRESHOLD:
            nr = config.NEEDS_REVIEW_CELL
            return min(nr[0], grid.rows - 1), min(nr[1], grid.cols - 1)

        # Try name lookup in the map
        if card.name in self.label_to_cell_map:
            r, c = self.label_to_cell_map[card.name]
            return min(r, grid.rows - 1), min(c, grid.cols - 1)

        # Try using raw CNN output fields
        if card.raw_cnn_output:
            top = card.raw_cnn_output.get("top_predictions", [])
            if top:
                best_label = top[0].get("label", "")
                if best_label in self.label_to_cell_map:
                    r, c = self.label_to_cell_map[best_label]
                    return min(r, grid.rows - 1), min(c, grid.cols - 1)

        # Fall back to rule-based
        return self._fallback.assign_cell(card, grid)

    @staticmethod
    def format_cnn_input(card: CardData) -> dict[str, Any]:
        """
        Produce the standardized dict to send TO the CNN model.

        Shape matches what CNNSorter.from_cnn_dict() expects back.
        """
        return {
            "card_id": card.card_id,
            "name": card.name,
            "set_code": card.set_code,
            "rarity": card.rarity,
            "class": card.hero_class,
            "price_usd": card.price_usd,
            "confidence": card.confidence,
            "top_predictions": [],
        }
