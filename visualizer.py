# ---------------------------------------------------------------------------
# visualizer.py  —  Matplotlib animated 2D top-down gantry view
# ---------------------------------------------------------------------------
from __future__ import annotations
from typing import TYPE_CHECKING

import config
from grid import CardGrid
from gantry import Gantry

if TYPE_CHECKING:
    from simulation import SortEvent


# ---------------------------------------------------------------------------
# Rarity color palette
# ---------------------------------------------------------------------------

RARITY_COLORS: dict[str, str] = {
    "F":  "#FFD700",   # Fabled     — gold
    "L":  "#9B59B6",   # Legendary  — purple
    "M":  "#E67E22",   # Majestic   — orange
    "CF": "#C0C0C0",   # Cold Foil  — silver
    "S":  "#BDC3C7",   # Super Rare — light silver
    "R":  "#3498DB",   # Rare       — blue
    "C":  "#95A5A6",   # Common     — grey
    "T":  "#ECF0F1",   # Token      — near white
}
EMPTY_COLOR = "#FFFFFF"
REVIEW_COLOR = "#E74C3C"  # needs-review cell — red


class Visualizer:
    """
    Matplotlib visualizer for the card sorter simulation.

    Layout: two subplots side by side.
      Left  — top-down gantry view (mm coordinates)
      Right — grid state table (abbreviated card names, color-coded by rarity)

    Call setup() before the simulation starts, then update(event) after
    each card is placed.  save_snapshot(path) writes the current figure to PNG.
    """

    def __init__(
        self,
        grid: CardGrid,
        gantry: Gantry,
        pause_s: float = 0.4,
    ) -> None:
        self.grid = grid
        self.gantry = gantry
        self._pause_s = pause_s
        self._fig = None
        self._ax_gantry = None
        self._ax_table = None
        self._initialized = False

    def setup(self) -> None:
        """Create the figure. Call once before sim.run()."""
        try:
            import matplotlib
            matplotlib.use("TkAgg")  # works on Windows; falls back gracefully
        except Exception:
            pass

        try:
            import matplotlib.pyplot as plt
            self._plt = plt
        except ImportError:
            print("[Visualizer] matplotlib not installed — visualization disabled.")
            return

        self._fig, (self._ax_gantry, self._ax_table) = self._plt.subplots(
            1, 2, figsize=(14, 7)
        )
        self._fig.suptitle("FaB Card Sorter — Simulation", fontsize=13, fontweight="bold")
        self._plt.tight_layout(rect=[0, 0, 1, 0.95])
        self._initialized = True
        self._draw(last_event=None)
        self._plt.pause(0.01)

    def update(self, last_event: "SortEvent | None" = None) -> None:
        """Redraw after a card is placed. Call after each sort event."""
        if not self._initialized:
            return
        self._draw(last_event)
        self._plt.pause(self._pause_s)

    def save_snapshot(self, filepath: str) -> None:
        """Save the current figure to a PNG file."""
        if not self._initialized:
            return
        self._fig.savefig(filepath, dpi=120, bbox_inches="tight")
        print(f"[Visualizer] Snapshot saved to {filepath}")

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _draw(self, last_event: "SortEvent | None") -> None:
        self._ax_gantry.cla()
        self._ax_table.cla()
        self._draw_gantry(last_event)
        self._draw_table(last_event)
        self._fig.canvas.draw_idle()

    def _draw_gantry(self, last_event: "SortEvent | None") -> None:
        import matplotlib.patches as mpatches

        ax = self._ax_gantry
        g = self.grid
        gantry_x, gantry_y, gantry_z = self.gantry.get_position()

        # --- Grid cells ---
        for r in range(g.rows):
            for c in range(g.cols):
                cell = g.get_cell(r, c)
                # Top-left corner of this cell
                x0 = cell.center_x_mm - g.cell_width_mm / 2
                y0 = cell.center_y_mm - g.cell_height_mm / 2

                # Is this the needs-review cell?
                nr = config.NEEDS_REVIEW_CELL
                if (r, c) == (min(nr[0], g.rows - 1), min(nr[1], g.cols - 1)):
                    face = REVIEW_COLOR if cell.is_empty else RARITY_COLORS.get(
                        cell.occupant.rarity if cell.occupant else "", REVIEW_COLOR
                    )
                elif cell.is_empty:
                    face = EMPTY_COLOR
                else:
                    rarity = cell.occupant.rarity if cell.occupant else "C"
                    face = RARITY_COLORS.get(rarity, EMPTY_COLOR)

                rect = mpatches.FancyBboxPatch(
                    (x0, y0), g.cell_width_mm, g.cell_height_mm,
                    boxstyle="round,pad=1",
                    facecolor=face,
                    edgecolor="#555555",
                    linewidth=1.0,
                )
                ax.add_patch(rect)

                # Cell label
                ax.text(
                    cell.center_x_mm, cell.center_y_mm + g.cell_height_mm * 0.3,
                    cell.label, ha="center", va="center",
                    fontsize=6, color="#333333",
                )
                # Count
                if cell.card_count > 0:
                    ax.text(
                        cell.center_x_mm, cell.center_y_mm,
                        f"{cell.card_count}x", ha="center", va="center",
                        fontsize=8, fontweight="bold", color="#000000",
                    )
                    if cell.occupant:
                        ax.text(
                            cell.center_x_mm,
                            cell.center_y_mm - g.cell_height_mm * 0.25,
                            cell.occupant.short_name,
                            ha="center", va="center",
                            fontsize=6, color="#000000",
                        )

        # --- Stack position ---
        sw, sh = 40.0, 40.0
        sx = config.STACK_X_MM - sw / 2
        sy = config.STACK_Y_MM - sh / 2
        stack_rect = mpatches.FancyBboxPatch(
            (sx, sy), sw, sh,
            boxstyle="round,pad=1",
            facecolor="#2ECC71",
            edgecolor="#27AE60",
            linewidth=2.0,
        )
        ax.add_patch(stack_rect)
        ax.text(
            config.STACK_X_MM, config.STACK_Y_MM,
            f"STACK\n{self.grid.rows * self.grid.cols}",   # show remaining visually
            ha="center", va="center", fontsize=7, fontweight="bold", color="white",
        )

        # --- Gantry crosshair ---
        ch_size = 15.0
        ax.plot(
            [gantry_x - ch_size, gantry_x + ch_size],
            [gantry_y, gantry_y],
            color="#E74C3C", linewidth=2.0, zorder=10,
        )
        ax.plot(
            [gantry_x, gantry_x],
            [gantry_y - ch_size, gantry_y + ch_size],
            color="#E74C3C", linewidth=2.0, zorder=10,
        )
        ax.plot(gantry_x, gantry_y, "ro", markersize=5, zorder=11)

        # --- Last move path ---
        if last_event:
            sx2, sy2 = last_event.source_pos
            tx2, ty2 = last_event.target_pos
            ax.annotate(
                "", xy=(tx2, ty2), xytext=(sx2, sy2),
                arrowprops=dict(
                    arrowstyle="->", color="#E74C3C",
                    lw=1.5, linestyle="dashed",
                ),
                zorder=9,
            )

        # --- Axis formatting ---
        total_w = g.origin_x_mm + g.width_mm + 20
        total_h = g.origin_y_mm + g.height_mm + 20
        ax.set_xlim(-10, total_w)
        ax.set_ylim(-10, total_h)
        ax.set_xlabel("X (mm)")
        ax.set_ylabel("Y (mm)")
        ax.set_title(
            f"Gantry: ({gantry_x:.0f}, {gantry_y:.0f})mm  "
            f"Z={gantry_z:.1f}mm  "
            f"t={self.gantry.get_simulated_time():.2f}s",
            fontsize=9,
        )
        ax.set_aspect("equal", adjustable="box")
        ax.grid(True, linestyle=":", linewidth=0.4, alpha=0.5)

        # --- Legend ---
        legend_patches = [
            mpatches.Patch(color=col, label=config.RARITY_NAMES.get(r, r))
            for r, col in RARITY_COLORS.items()
        ]
        legend_patches.append(mpatches.Patch(color=REVIEW_COLOR, label="Needs Review"))
        ax.legend(
            handles=legend_patches,
            loc="upper right",
            fontsize=6,
            ncol=2,
            framealpha=0.8,
        )

    def _draw_table(self, last_event: "SortEvent | None") -> None:
        ax = self._ax_table
        g = self.grid

        snapshot = g.get_grid_snapshot()

        col_labels = [f"Col {c}" for c in range(g.cols)]
        row_labels = [f"Row {r}" for r in range(g.rows)]

        cell_text: list[list[str]] = []
        cell_colors: list[list[str]] = []

        for r in range(g.rows):
            row_txt = []
            row_col = []
            for c in range(g.cols):
                cell = snapshot[r][c]
                if cell.is_empty:
                    row_txt.append("—")
                    row_col.append(EMPTY_COLOR)
                else:
                    name = cell.occupant.short_name if cell.occupant else "?"
                    rarity = cell.occupant.rarity if cell.occupant else "C"
                    row_txt.append(f"{name}\n[{rarity}] x{cell.card_count}")
                    row_col.append(RARITY_COLORS.get(rarity, EMPTY_COLOR))
            cell_text.append(row_txt)
            cell_colors.append(row_col)

        ax.axis("off")
        table = ax.table(
            cellText=cell_text,
            cellColours=cell_colors,
            rowLabels=row_labels,
            colLabels=col_labels,
            loc="center",
            cellLoc="center",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(7)
        table.scale(1.2, 2.2)

        stats = g.get_stats()
        event_info = ""
        if last_event and last_event.card:
            card = last_event.card
            event_info = (
                f"Last: {card.name} [{card.rarity_name}]  "
                f"-> cell {last_event.target_cell}  "
                f"${card.price_usd:.2f}"
            )

        ax.set_title(
            f"Grid State  ({stats['occupied_cells']}/{stats['total_cells']} cells)    "
            + event_info,
            fontsize=9,
        )
