# ---------------------------------------------------------------------------
# grid.py  —  Physical card grid with mm coordinate mapping
# ---------------------------------------------------------------------------
from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import config

if TYPE_CHECKING:
    from card import CardData


class CellFullError(Exception):
    """Raised when trying to place a card in a cell that is at capacity."""


class GridShrinkError(Exception):
    """Raised when resizing would orphan occupied cells."""


@dataclass
class GridCell:
    """
    One slot in the sorting grid.

    A cell can hold a physical stack of cards (card_count tracks depth).
    `occupant` stores the most recently placed card for display purposes.
    """
    row: int
    col: int
    center_x_mm: float
    center_y_mm: float
    label: str                          # e.g. "R0C2"
    occupant: "CardData | None" = field(default=None, repr=False)
    card_count: int = 0
    capacity: int = 50                  # max physical cards in this cell

    @property
    def is_empty(self) -> bool:
        return self.card_count == 0

    @property
    def is_full(self) -> bool:
        return self.card_count >= self.capacity

    def __repr__(self) -> str:
        status = f"{self.card_count}x" if self.card_count > 0 else "empty"
        return f"GridCell({self.label}, {status})"


class CardGrid:
    """
    A configurable grid of GridCell objects, each mapped to real mm coordinates.

    Origin is the center of cell (0, 0).  Cells are laid out in row-major order
    with row 0 at the top (smallest Y) and col 0 at the left (smallest X).
    """

    def __init__(
        self,
        rows: int | None = None,
        cols: int | None = None,
        cell_width_mm: float | None = None,
        cell_height_mm: float | None = None,
        origin_x_mm: float | None = None,
        origin_y_mm: float | None = None,
        cell_capacity: int = 50,
    ) -> None:
        self._rows = rows or config.GRID_ROWS
        self._cols = cols or config.GRID_COLS
        self._cell_w = cell_width_mm or config.GRID_CELL_WIDTH_MM
        self._cell_h = cell_height_mm or config.GRID_CELL_HEIGHT_MM
        self._origin_x = origin_x_mm if origin_x_mm is not None else config.GRID_ORIGIN_X_MM
        self._origin_y = origin_y_mm if origin_y_mm is not None else config.GRID_ORIGIN_Y_MM
        self._cell_capacity = cell_capacity
        self._cells: dict[tuple[int, int], GridCell] = {}
        self._total_placed: int = 0

        self._build_cells()

    # ------------------------------------------------------------------
    # Cell construction
    # ------------------------------------------------------------------

    def _build_cells(self) -> None:
        """(Re)build the cell dict for current rows/cols."""
        for r in range(self._rows):
            for c in range(self._cols):
                cx = self._origin_x + c * self._cell_w
                cy = self._origin_y + r * self._cell_h
                key = (r, c)
                if key not in self._cells:
                    # New cell — create fresh
                    self._cells[key] = GridCell(
                        row=r,
                        col=c,
                        center_x_mm=cx,
                        center_y_mm=cy,
                        label=f"R{r}C{c}",
                        capacity=self._cell_capacity,
                    )
                else:
                    # Existing cell — update coordinates only
                    self._cells[key].center_x_mm = cx
                    self._cells[key].center_y_mm = cy

    # ------------------------------------------------------------------
    # Resize
    # ------------------------------------------------------------------

    def resize(self, rows: int, cols: int) -> None:
        """
        Expand or contract the grid.

        Raises GridShrinkError if shrinking would remove occupied cells.
        The visualizer will auto-scale on its next update() call.
        """
        # Safety check: don't orphan occupied cells
        for (r, c), cell in self._cells.items():
            if not cell.is_empty and (r >= rows or c >= cols):
                raise GridShrinkError(
                    f"Cannot shrink grid to {rows}x{cols}: "
                    f"cell {cell.label} has {cell.card_count} card(s)."
                )

        # Remove cells that are now out of range and empty
        to_remove = [k for k in self._cells if k[0] >= rows or k[1] >= cols]
        for k in to_remove:
            del self._cells[k]

        self._rows = rows
        self._cols = cols
        self._build_cells()

    # ------------------------------------------------------------------
    # Card placement
    # ------------------------------------------------------------------

    def place_card(self, row: int, col: int, card: "CardData") -> None:
        """Place a card into a cell. Raises CellFullError if at capacity."""
        cell = self.get_cell(row, col)
        if cell.is_full:
            raise CellFullError(
                f"Cell {cell.label} is full ({cell.card_count}/{cell.capacity} cards)."
            )
        cell.occupant = card
        cell.card_count += 1
        self._total_placed += 1

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_cell(self, row: int, col: int) -> GridCell:
        key = (row, col)
        if key not in self._cells:
            raise KeyError(f"Cell ({row}, {col}) does not exist in this {self._rows}x{self._cols} grid.")
        return self._cells[key]

    def get_cell_position(self, row: int, col: int) -> tuple[float, float]:
        """Return (center_x_mm, center_y_mm) for a cell."""
        cell = self.get_cell(row, col)
        return cell.center_x_mm, cell.center_y_mm

    def find_empty_cell(self) -> GridCell | None:
        """Return the first empty cell in row-major order, or None if grid is full."""
        for r in range(self._rows):
            for c in range(self._cols):
                cell = self._cells[(r, c)]
                if not cell.is_full:
                    return cell
        return None

    def find_cell_in_row(self, row: int) -> GridCell | None:
        """Return first non-full cell in the given row."""
        for c in range(self._cols):
            cell = self._cells.get((row, c))
            if cell and not cell.is_full:
                return cell
        return None

    def get_all_cells(self) -> list[GridCell]:
        """All cells in row-major order."""
        return [self._cells[(r, c)] for r in range(self._rows) for c in range(self._cols)]

    def get_grid_snapshot(self) -> list[list[GridCell]]:
        """2D list of cells — snapshot for visualizer / reporting."""
        return [
            [self._cells[(r, c)] for c in range(self._cols)]
            for r in range(self._rows)
        ]

    def get_stats(self) -> dict:
        all_cells = self.get_all_cells()
        occupied = sum(1 for c in all_cells if not c.is_empty)
        return {
            "rows": self._rows,
            "cols": self._cols,
            "total_cells": len(all_cells),
            "occupied_cells": occupied,
            "empty_cells": len(all_cells) - occupied,
            "total_cards_placed": self._total_placed,
        }

    # ------------------------------------------------------------------
    # Properties for external use (e.g. visualizer)
    # ------------------------------------------------------------------

    @property
    def rows(self) -> int:
        return self._rows

    @property
    def cols(self) -> int:
        return self._cols

    @property
    def cell_width_mm(self) -> float:
        return self._cell_w

    @property
    def cell_height_mm(self) -> float:
        return self._cell_h

    @property
    def origin_x_mm(self) -> float:
        return self._origin_x

    @property
    def origin_y_mm(self) -> float:
        return self._origin_y

    @property
    def width_mm(self) -> float:
        """Total grid width in mm."""
        return self._cols * self._cell_w

    @property
    def height_mm(self) -> float:
        """Total grid height in mm."""
        return self._rows * self._cell_h

    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"CardGrid({self._rows}x{self._cols}, "
            f"{stats['occupied_cells']}/{stats['total_cells']} cells occupied, "
            f"{stats['total_cards_placed']} cards placed)"
        )
