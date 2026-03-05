# ---------------------------------------------------------------------------
# simulation.py  —  Main orchestration loop, pick/drop sequences, event log
# ---------------------------------------------------------------------------
from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Callable, Any

import config
from card import CardData, InputStack, StackEmptyError
from grid import CardGrid, GridCell
from gantry import Gantry, MoveRecord
from sorter import SortingStrategy, FaBRuleBasedSorter


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SortEvent:
    """One complete pick+drop cycle for a single card."""
    event_type: str                         # "PICK", "DROP", "HOME", "ERROR"
    card: CardData | None
    source_pos: tuple[float, float]         # mm (x, y) — stack position
    target_pos: tuple[float, float]         # mm (x, y) — cell center
    target_cell: tuple[int, int] | None     # (row, col)
    timestamp_s: float                      # sim clock at PICK moment
    pick_moves: list[MoveRecord] = field(default_factory=list, repr=False)
    drop_moves: list[MoveRecord] = field(default_factory=list, repr=False)
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "card": self.card.to_dict() if self.card else None,
            "source_pos": list(self.source_pos),
            "target_pos": list(self.target_pos),
            "target_cell": list(self.target_cell) if self.target_cell else None,
            "timestamp_s": round(self.timestamp_s, 4),
            "notes": self.notes,
        }


@dataclass
class SimulationReport:
    """Summary produced at the end of sim.run()."""
    cards_processed: int
    total_simulated_time_s: float
    total_distance_mm: float
    total_moves: int
    errors: list[str]
    grid_stats: dict
    event_count_by_type: dict[str, int]

    def __str__(self) -> str:
        lines = [
            "=" * 52,
            "  SIMULATION REPORT",
            "=" * 52,
            f"  Cards processed    : {self.cards_processed}",
            f"  Simulated time     : {self.total_simulated_time_s:.3f} s",
            f"  Total travel       : {self.total_distance_mm:.1f} mm",
            f"  Total moves        : {self.total_moves}",
            f"  Grid               : {self.grid_stats.get('rows')}x{self.grid_stats.get('cols')}",
            f"  Cells occupied     : {self.grid_stats.get('occupied_cells')}/{self.grid_stats.get('total_cells')}",
            f"  Errors             : {len(self.errors)}",
            "=" * 52,
        ]
        if self.errors:
            lines.append("  Errors:")
            for e in self.errors:
                lines.append(f"    - {e}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

class Simulation:
    """
    Orchestrates the pick-and-place sorting loop.

    Owns the gantry, grid, stack, and sorter.  Drives them in sequence:
        home -> repeat { peek -> cnn_hook? -> assign_cell -> pick -> drop } -> report

    CNN hook:
        sim.set_cnn_hook(fn)
        fn receives the CardData about to be sorted and must return a dict
        (raw CNN output).  The dict is written to card.raw_cnn_output
        before assign_cell is called, simulating a live camera feed.
    """

    def __init__(
        self,
        gantry: Gantry,
        grid: CardGrid,
        stack: InputStack,
        sorter: SortingStrategy | None = None,
        event_log_path: str | None = None,
    ) -> None:
        self.gantry = gantry
        self.grid = grid
        self.stack = stack
        self.sorter: SortingStrategy = sorter or FaBRuleBasedSorter()
        self._log_path = event_log_path

        self._event_log: list[SortEvent] = []
        self._errors: list[str] = []
        self._cnn_hook: Callable[[CardData], dict] | None = None
        self._visualizer = None  # set via attach_visualizer()

        # Open log file if requested
        self._log_file = None
        if event_log_path:
            self._log_file = open(event_log_path, "w", encoding="utf-8")

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_cnn_hook(self, fn: Callable[[CardData], dict]) -> None:
        """
        Register a live CNN hook.

        fn(card) -> dict  will be called for each card before assign_cell.
        The returned dict is written to card.raw_cnn_output and its
        'confidence' key (if present) is written to card.confidence.

        Example:
            def my_model(card):
                # call your TFLite / REST model here
                return {"name": card.name, "confidence": 0.97, ...}
            sim.set_cnn_hook(my_model)
        """
        self._cnn_hook = fn

    def set_sorter(self, sorter: SortingStrategy) -> None:
        """Swap out the sorting strategy at runtime."""
        self.sorter = sorter

    def attach_visualizer(self, visualizer) -> None:
        self._visualizer = visualizer

    def resize_grid(self, rows: int, cols: int) -> None:
        """Resize the grid. Visualizer auto-scales on next update()."""
        self.grid.resize(rows, cols)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self, max_cards: int | None = None) -> SimulationReport:
        """
        Process cards from the stack until empty or max_cards is reached.

        Returns a SimulationReport.
        """
        print(f"\n{'='*52}")
        print(f"  STARTING SORT — {self.stack.remaining()} cards in stack")
        print(f"  Grid: {self.grid.rows}x{self.grid.cols}  |  "
              f"Sorter: {type(self.sorter).__name__}")
        print(f"{'='*52}\n")

        self.gantry.home()

        processed = 0
        while not self.stack.is_empty():
            if max_cards is not None and processed >= max_cards:
                break
            try:
                event = self._process_next_card()
                self._log_event(event)
                if self._visualizer:
                    self._visualizer.update(event)
                processed += 1
                self._print_grid_snapshot()
            except Exception as exc:
                msg = f"Error on card #{processed + 1}: {exc}"
                self._errors.append(msg)
                print(f"  [ERROR] {msg}")
                # Skip the bad card so the run continues
                if not self.stack.is_empty():
                    self.stack.pop()

        # Return home at the end
        self.gantry.move_xy(0.0, 0.0)
        self.gantry.move_z(0.0)

        if self._log_file:
            self._log_file.close()

        report = SimulationReport(
            cards_processed=processed,
            total_simulated_time_s=self.gantry.get_simulated_time(),
            total_distance_mm=self.gantry.get_total_distance(),
            total_moves=len(self.gantry.get_move_history()),
            errors=list(self._errors),
            grid_stats=self.grid.get_stats(),
            event_count_by_type=self._count_events(),
        )
        print(f"\n{report}")
        return report

    # ------------------------------------------------------------------
    # Per-card processing
    # ------------------------------------------------------------------

    def _process_next_card(self) -> SortEvent:
        """Pick one card from the stack and drop it in the sorted position."""
        card = self.stack.peek()
        if card is None:
            raise StackEmptyError("Stack is empty.")

        # --- CNN hook (live feed simulation) ---
        if self._cnn_hook is not None:
            cnn_result = self._cnn_hook(card)
            card.raw_cnn_output = cnn_result
            if "confidence" in cnn_result:
                card.confidence = float(cnn_result["confidence"])

        # --- Assign destination ---
        target_row, target_col = self.sorter.assign_cell(card, self.grid)
        target_x, target_y = self.grid.get_cell_position(target_row, target_col)
        source_x, source_y = config.STACK_X_MM, config.STACK_Y_MM
        timestamp = self.gantry.get_simulated_time()

        # --- Pick ---
        pick_moves = self._pick_card(source_x, source_y, card)

        # Commit pop AFTER the physical pick (head has touched the card)
        self.stack.pop()

        # --- Drop ---
        drop_moves = self._drop_card(target_x, target_y, card)

        # --- Place in grid ---
        self.grid.place_card(target_row, target_col, card)

        event = SortEvent(
            event_type="SORT",
            card=card,
            source_pos=(source_x, source_y),
            target_pos=(target_x, target_y),
            target_cell=(target_row, target_col),
            timestamp_s=timestamp,
            pick_moves=pick_moves,
            drop_moves=drop_moves,
        )
        return event

    def _pick_card(
        self,
        stack_x: float,
        stack_y: float,
        card: CardData,
    ) -> list[MoveRecord]:
        """Move to stack, lower Z (pick up), raise Z. Prints CoreXY gantry trace."""
        moves: list[MoveRecord] = []

        # Capture motor positions before XY move
        a_before = self.gantry.motor_a.get_step_count()
        b_before = self.gantry.motor_b.get_step_count()

        # Move XY to above the stack
        rec_xy = self.gantry.move_xy(stack_x, stack_y)
        moves.append(rec_xy)

        a_delta = self.gantry.motor_a.get_step_count() - a_before
        b_delta = self.gantry.motor_b.get_step_count() - b_before
        t = self.gantry.get_simulated_time()
        x, y, _ = self.gantry.get_position()
        if rec_xy.distance_mm > 1e-3:
            print(
                f"[t={t:>7.3f}s] XY    "
                f"X:{x:>6.1f}mm  Y:{y:>6.1f}mm  "
                f"dist:{rec_xy.distance_mm:.1f}mm  "
                f"A:{a_delta:+d}  B:{b_delta:+d} steps"
            )

        # Lower Z to pick height
        rec_z_down = self.gantry.move_z(config.Z_TRAVEL_MM)
        moves.append(rec_z_down)
        t = self.gantry.get_simulated_time()
        print(f"[t={t:>7.3f}s] Z-DN  Z:{config.Z_TRAVEL_MM:.1f}mm  (approaching card)")

        # --- PICK event ---
        t = self.gantry.get_simulated_time()
        x, y, z = self.gantry.get_position()
        print(
            f"[t={t:>7.3f}s] PICK  {card.card_id:<8} "
            f"\"{card.name}\" [{card.rarity_name}]  "
            f"@ ({x:.1f}, {y:.1f}, {z:.1f})mm  "
            f"{self.stack.remaining()} left in input"
        )

        # Raise Z (card is now "held")
        rec_z_up = self.gantry.move_z(0.0)
        moves.append(rec_z_up)
        t = self.gantry.get_simulated_time()
        print(f"[t={t:>7.3f}s] Z-UP  Z:0.0mm   (card lifted, transiting)")

        return moves

    def _drop_card(
        self,
        cell_x: float,
        cell_y: float,
        card: CardData,
    ) -> list[MoveRecord]:
        """Move to cell, lower Z (release card), raise Z. Prints CoreXY gantry trace."""
        moves: list[MoveRecord] = []

        # Capture motor positions before XY move
        a_before = self.gantry.motor_a.get_step_count()
        b_before = self.gantry.motor_b.get_step_count()

        # Move XY to above the target cell
        rec_xy = self.gantry.move_xy(cell_x, cell_y)
        moves.append(rec_xy)

        a_delta = self.gantry.motor_a.get_step_count() - a_before
        b_delta = self.gantry.motor_b.get_step_count() - b_before
        t = self.gantry.get_simulated_time()
        x, y, _ = self.gantry.get_position()
        if rec_xy.distance_mm > 1e-3:
            print(
                f"[t={t:>7.3f}s] XY    "
                f"X:{x:>6.1f}mm  Y:{y:>6.1f}mm  "
                f"dist:{rec_xy.distance_mm:.1f}mm  "
                f"A:{a_delta:+d}  B:{b_delta:+d} steps"
            )

        # Lower Z to drop height
        rec_z_down = self.gantry.move_z(config.Z_TRAVEL_MM)
        moves.append(rec_z_down)
        t = self.gantry.get_simulated_time()
        print(f"[t={t:>7.3f}s] Z-DN  Z:{config.Z_TRAVEL_MM:.1f}mm  (placing card)")

        # --- DROP event ---
        t = self.gantry.get_simulated_time()
        x, y, z = self.gantry.get_position()
        print(
            f"[t={t:>7.3f}s] DROP  {card.card_id:<8} "
            f"\"{card.name}\" [{card.rarity_name}]  "
            f"-> ({x:.1f}, {y:.1f}, {z:.1f})mm  "
            f"${card.price_usd:.2f}"
        )

        # Raise Z (card released, head lifts clear)
        rec_z_up = self.gantry.move_z(0.0)
        moves.append(rec_z_up)
        t = self.gantry.get_simulated_time()
        print(f"[t={t:>7.3f}s] Z-UP  Z:0.0mm   (head clear)")

        return moves

    def _print_grid_snapshot(self) -> None:
        """Print a terminal table showing card stack count for every grid cell."""
        snapshot = self.grid.get_grid_snapshot()
        cols = self.grid.cols
        cw = 13  # column width (chars)
        div = "  +" + ("-" * cw + "+") * cols

        print(f"\n  -- Grid Snapshot --")
        print(div)
        for row in snapshot:
            line_label = "  |"
            line_count = "  |"
            for cell in row:
                label = f" {cell.label}"
                line_label += f"{label:<{cw}}|"
                if cell.card_count == 0:
                    count_str = " empty"
                elif cell.card_count == 1:
                    count_str = f" 1 card"
                else:
                    count_str = f" {cell.card_count} cards"
                line_count += f"{count_str:<{cw}}|"
            print(line_label)
            print(line_count)
            print(div)
        print()

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log_event(self, event: SortEvent) -> None:
        self._event_log.append(event)
        if self._log_file:
            self._log_file.write(json.dumps(event.to_dict()) + "\n")
            self._log_file.flush()

    def _count_events(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self._event_log:
            counts[e.event_type] = counts.get(e.event_type, 0) + 1
        return counts

    def export_log_json(self, filepath: str) -> None:
        """Write the full event log as a JSON array."""
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump([e.to_dict() for e in self._event_log], f, indent=2)
        print(f"  Event log written to {filepath}")

    def get_event_log(self) -> list[SortEvent]:
        return list(self._event_log)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def __del__(self) -> None:
        if self._log_file and not self._log_file.closed:
            self._log_file.close()
