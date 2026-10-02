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


# ---------------------------------------------------------------------------
# MultiGameSorter  —  rarity- or type-row sorting for any game the
#                     fab-card-id identify service knows (riftbound, magic,
#                     pokemon, fab).  Tier tables live in config.
# ---------------------------------------------------------------------------

class MultiGameSorter:
    """
    Row = the card's tier (rarity or primary type) in the active game's
    tier list; column fills left to right.  Cards below the confidence
    threshold go to NEEDS_REVIEW_CELL; cards positively identified as a
    different game go to OTHER_GAME_CELL; unknown tiers land on the last
    row (bulk).
    """

    def __init__(self, game: str, mode: str = "rarity") -> None:
        if mode not in ("rarity", "type", "price"):
            raise ValueError(f"mode must be rarity/type/price, got {mode!r}")
        self.game = game
        self.mode = mode
        if mode == "price":
            tiers = [label for label, _ in config.PRICE_TIERS_CAD]
        else:
            tiers = (config.MULTIGAME_RARITY_TIERS if mode == "rarity"
                     else config.MULTIGAME_TYPE_ORDERS).get(game, [])
        self._tier_row = {t.lower(): i for i, t in enumerate(tiers)}

    @staticmethod
    def _price_of(card: CardData):
        return (card.raw_cnn_output or {}).get("price")

    def _price_tier(self, price) -> str:
        """Label of the price band a CAD price falls in; '' if no price."""
        if price is None:
            return ""
        for label, floor in config.PRICE_TIERS_CAD:
            if price >= floor:
                return label
        return config.PRICE_TIERS_CAD[-1][0]

    def tier_of(self, card: CardData) -> str:
        raw = card.raw_cnn_output or {}
        if self.mode == "price":
            return self._price_tier(self._price_of(card))
        if self.mode == "rarity":
            return card.rarity or raw.get("rarity", "")
        # Primary type: first word of the type line handles Magic's
        # "Legendary Creature — Elf" via containment below.
        return raw.get("type_line", "") or getattr(card, "type_line", "")

    def _tier_index(self, tier: str) -> int | None:
        t = tier.lower()
        if t in self._tier_row:
            return self._tier_row[t]
        # Magic type lines embed the primary type ("Legendary Creature — …").
        for name, i in self._tier_row.items():
            if name in t:
                return i
        return None

    def _tier_known(self, card: CardData) -> bool:
        """A low-confidence card is still placeable if the match AND every
        ambiguous candidate agree on this sort's tier — the exact printing is
        uncertain, but the rarity/type bin is not.  (Alt-art variants that span
        rarities disagree here, so they still go to review.)"""
        tier = self.tier_of(card)
        if self._tier_index(tier) is None:
            return False
        # Price is printing-specific (candidates carry no price), so an
        # ambiguous printing can't be confidently price-binned — review it.
        if self.mode == "price":
            return False
        for c in (card.raw_cnn_output or {}).get("candidates", []):
            ctier = (c.get("rarity", "") if self.mode == "rarity"
                     else c.get("type_line", ""))
            if self._tier_index(ctier) != self._tier_index(tier):
                return False
        return True

    def placement_kind(self, card: CardData) -> str:
        """Classify where a card is headed — 'other', 'review', or 'sorted' —
        matching assign_cell's branching, so stats are correct even though the
        review/other cells geometrically sit inside tier rows."""
        raw = card.raw_cnn_output or {}
        if raw.get("confidence_str") == "foreign":
            return "other"
        if card.confidence < config.CNN_CONFIDENCE_THRESHOLD and not self._tier_known(card):
            return "review"
        return "sorted"

    def assign_cell(self, card: CardData, grid: CardGrid) -> tuple[int, int]:
        raw = card.raw_cnn_output or {}
        if raw.get("confidence_str") == "foreign":
            return (min(config.OTHER_GAME_CELL[0], grid.rows - 1),
                    min(config.OTHER_GAME_CELL[1], grid.cols - 1))
        # Review only when we genuinely can't place it: unidentified, or
        # low-confidence AND the printing ambiguity spans different tiers.
        if card.confidence < config.CNN_CONFIDENCE_THRESHOLD and not self._tier_known(card):
            return (min(config.NEEDS_REVIEW_CELL[0], grid.rows - 1),
                    min(config.NEEDS_REVIEW_CELL[1], grid.cols - 1))
        idx = self._tier_index(self.tier_of(card))
        row = grid.rows - 1 if idx is None else min(idx, grid.rows - 1)
        for c in range(grid.cols):
            if not grid.get_cell(row, c).is_full:
                return row, c
        cell = grid.find_empty_cell()
        if cell:
            return cell.row, cell.col
        return grid.rows - 1, grid.cols - 1

    def describe(self, card: CardData, cell: tuple[int, int]) -> str:
        """Human-readable reason for the UI's sort-decision panel."""
        raw = card.raw_cnn_output or {}
        if raw.get("confidence_str") == "foreign":
            return "not this game -> other-game pile"
        low = card.confidence < config.CNN_CONFIDENCE_THRESHOLD
        if low and not self._tier_known(card):
            return f"low confidence ({raw.get('confidence_str', '?')}) -> review"
        tier = self.tier_of(card)
        idx = self._tier_index(tier)
        if self.mode == "price":
            price = self._price_of(card)
            if price is None:
                return "no price available -> bottom row"
            return f"${price:.2f} -> {tier} row"
        if idx is None:
            return f"{self.mode} '{tier or 'unknown'}' not in tier list -> bulk row"
        if low:
            return f"{self.mode} '{tier}' (printing uncertain) -> row {cell[0]}"
        return f"{self.mode} '{tier}' -> row {cell[0]}"
