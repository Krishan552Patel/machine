# ---------------------------------------------------------------------------
# main.py  —  Entry point for the FaB card sorter simulation
#
# Usage:
#   python main.py                  # default 4x4 grid, 16 sample cards
#   python main.py --grid 6x6       # 6-row x 6-col grid
#   python main.py --strategy by_rarity
#   python main.py --no-viz         # run headless (text output only)
#   python main.py --cards 8        # sort only the first 8 cards
#   python main.py --log run.json   # export event log to JSON
# ---------------------------------------------------------------------------
from __future__ import annotations
import argparse
import sys

import config
from card import CardData, InputStack
from grid import CardGrid
from gantry import Gantry, CoreXYKinematics
from motor import StepperMotor
from sorter import FaBRuleBasedSorter, CNNSorter
from simulation import Simulation
from visualizer import Visualizer


# ---------------------------------------------------------------------------
# Sample deck  —  covers all FaB rarities across four sets
# ---------------------------------------------------------------------------

SAMPLE_DECK: list[dict] = [
    # Fabled / Legendary
    {"card_id": "WTR001", "name": "Dorinthea Ironsong",     "set_code": "WTR", "rarity": "L", "hero_class": "warrior",  "price_usd": 48.50},
    {"card_id": "MON001", "name": "Prism, Sculptor of Arc", "set_code": "MON", "rarity": "F", "hero_class": "illusionist","price_usd": 120.00},
    {"card_id": "ARC001", "name": "Ira, Crimson Haze",      "set_code": "ARC", "rarity": "L", "hero_class": "ninja",     "price_usd": 35.00},
    {"card_id": "EVO001", "name": "Bravo, Star of the Show","set_code": "EVO", "rarity": "L", "hero_class": "guardian",  "price_usd": 22.00},
    # Majestic / Super Rare
    {"card_id": "WTR010", "name": "Enlightened Strike",     "set_code": "WTR", "rarity": "M", "hero_class": "generic",  "price_usd": 8.75},
    {"card_id": "MON010", "name": "Codex of Frailty",       "set_code": "MON", "rarity": "M", "hero_class": "wizard",   "price_usd": 14.00},
    {"card_id": "ARC010", "name": "Mage Master Boots",      "set_code": "ARC", "rarity": "S", "hero_class": "generic",  "price_usd": 6.50},
    {"card_id": "CRU001", "name": "Cash In",                "set_code": "CRU", "rarity": "M", "hero_class": "merchant", "price_usd": 11.00},
    # Rare
    {"card_id": "WTR020", "name": "Dawnblade",              "set_code": "WTR", "rarity": "R", "hero_class": "warrior",  "price_usd": 3.50},
    {"card_id": "MON020", "name": "Spectral Shield",        "set_code": "MON", "rarity": "R", "hero_class": "illusionist","price_usd": 2.00},
    {"card_id": "ARC020", "name": "Harmonized Kodachi",     "set_code": "ARC", "rarity": "R", "hero_class": "ninja",    "price_usd": 4.25},
    {"card_id": "EVO010", "name": "Courage of Bladehold",   "set_code": "EVO", "rarity": "R", "hero_class": "generic",  "price_usd": 1.80},
    # Common / Token
    {"card_id": "WTR050", "name": "Warrior's Valor",        "set_code": "WTR", "rarity": "C", "hero_class": "warrior",  "price_usd": 0.25},
    {"card_id": "MON050", "name": "Fog of War",             "set_code": "MON", "rarity": "C", "hero_class": "generic",  "price_usd": 0.10},
    {"card_id": "ARC050", "name": "Surging Strike",         "set_code": "ARC", "rarity": "C", "hero_class": "ninja",    "price_usd": 0.15},
    {"card_id": "WTR099", "name": "Ponder Token",           "set_code": "WTR", "rarity": "T", "hero_class": "generic",  "price_usd": 0.05},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_gantry() -> Gantry:
    motor_a = StepperMotor(
        "A",
        steps_per_mm=config.STEPS_PER_MM,
        microsteps=config.MICROSTEPS,
        max_feedrate_mm_s=config.MAX_FEEDRATE_MM_S,
        acceleration_mm_s2=config.ACCELERATION_MM_S2,
    )
    motor_b = StepperMotor(
        "B",
        steps_per_mm=config.STEPS_PER_MM,
        microsteps=config.MICROSTEPS,
        max_feedrate_mm_s=config.MAX_FEEDRATE_MM_S,
        acceleration_mm_s2=config.ACCELERATION_MM_S2,
    )
    motor_z = StepperMotor(
        "Z",
        steps_per_mm=config.STEPS_PER_MM,
        microsteps=config.MICROSTEPS,
        max_feedrate_mm_s=config.Z_SPEED_MM_S,
        acceleration_mm_s2=config.Z_ACCELERATION_MM_S2,
    )
    return Gantry(motor_a, motor_b, motor_z, CoreXYKinematics())


def build_stack(deck: list[dict]) -> InputStack:
    cards = [CardData.from_dict(d) for d in deck]
    stack = InputStack()
    # Load bottom to top (last in list = top of stack = first sorted)
    stack.load_from_list(cards)
    return stack


def parse_grid_arg(grid_str: str) -> tuple[int, int]:
    try:
        rows_s, cols_s = grid_str.lower().split("x")
        return int(rows_s), int(cols_s)
    except ValueError:
        print(f"[Error] --grid must be in format ROWSxCOLS, e.g. 4x4 or 6x6")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Optional: CNN hook demo
# ---------------------------------------------------------------------------

def demo_cnn_hook(card: CardData) -> dict:
    """
    Simulates what a real CNN call would return.

    In production, replace the body with your actual model inference:
        result = requests.post(MODEL_URL, json=CNNSorter.format_cnn_input(card))
        return result.json()
    """
    return {
        "card_id": card.card_id,
        "name": card.name,
        "set_code": card.set_code,
        "rarity": card.rarity,
        "class": card.hero_class,
        "price_usd": card.price_usd,
        "confidence": 0.97,
        "top_predictions": [
            {"label": card.name, "score": 0.97},
            {"label": "Unknown Card", "score": 0.03},
        ],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="FaB Card Sorter Simulation")
    parser.add_argument("--grid", default="4x4", help="Grid dimensions e.g. 4x4 or 6x6")
    parser.add_argument(
        "--strategy",
        default="by_rarity_and_set",
        choices=["by_rarity", "by_set", "by_price", "by_rarity_and_set"],
        help="Sorting strategy",
    )
    parser.add_argument("--no-viz", action="store_true", help="Disable matplotlib visualization")
    parser.add_argument("--cards", type=int, default=None, help="Limit number of cards to sort")
    parser.add_argument("--log", default=None, help="Export event log to JSON file")
    parser.add_argument("--cnn-hook", action="store_true", help="Enable demo CNN hook")
    args = parser.parse_args()

    rows, cols = parse_grid_arg(args.grid)

    print(f"\n  FaB Card Sorter Simulation")
    print(f"  Grid: {rows}x{cols}  |  Strategy: {args.strategy}")
    print(f"  Cards in deck: {len(SAMPLE_DECK)}")

    # --- Build components ---
    gantry = build_gantry()
    grid = CardGrid(rows=rows, cols=cols)
    stack = build_stack(SAMPLE_DECK)
    sorter = FaBRuleBasedSorter(strategy=args.strategy)

    sim = Simulation(
        gantry=gantry,
        grid=grid,
        stack=stack,
        sorter=sorter,
        event_log_path=args.log,
    )

    # Optional CNN hook
    if args.cnn_hook:
        sim.set_cnn_hook(demo_cnn_hook)
        print("  CNN hook: ENABLED (demo mode)")

    # --- Visualizer ---
    if not args.no_viz:
        viz = Visualizer(grid, gantry, pause_s=0.5)
        sim.attach_visualizer(viz)
        try:
            viz.setup()
        except Exception as e:
            print(f"  [Visualizer] Could not initialize matplotlib ({e}). Running headless.")

    # --- Run ---
    report = sim.run(max_cards=args.cards)

    # --- Save final snapshot ---
    if not args.no_viz and sim._visualizer and sim._visualizer._initialized:
        sim._visualizer.save_snapshot("final_grid.png")

    # --- Export log if requested ---
    if args.log:
        sim.export_log_json(args.log)

    print(f"\n  Motor states at end of run:")
    for name, state in gantry.get_motor_states().items():
        print(f"    Motor {name}: {state['step_count']} steps  |  {state['position_mm']:.2f} mm")


if __name__ == "__main__":
    main()
