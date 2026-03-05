# ---------------------------------------------------------------------------
# run.py  —  Interactive launcher for the FaB card sorter simulation
#
# Usage:  python run.py
#   Shows a menu, lets you pick all options, then launches the simulation.
# ---------------------------------------------------------------------------
from __future__ import annotations
import os
import sys
import subprocess


# ── ANSI colours (works on Windows 10+ and most terminals) ──────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
DIM    = "\033[2m"


def cls():
    os.system("cls" if os.name == "nt" else "clear")


def header():
    cls()
    print(f"{BOLD}{CYAN}")
    print("  ╔══════════════════════════════════════════════════════╗")
    print("  ║        FaB Card Sorter  —  Simulation Launcher       ║")
    print("  ╚══════════════════════════════════════════════════════╝")
    print(RESET)


def section(title: str):
    print(f"\n{BOLD}{YELLOW}  ── {title} ──{RESET}")


def option(key: str, label: str, detail: str = ""):
    detail_str = f"  {DIM}{detail}{RESET}" if detail else ""
    print(f"  {GREEN}{key}{RESET}  {label}{detail_str}")


def prompt(msg: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    val = input(f"\n  {BOLD}{msg}{hint}: {RESET}").strip()
    return val if val else default


def pick(msg: str, choices: list[tuple[str, str, str]], default_key: str) -> str:
    """Display numbered choices, return the chosen value."""
    section(msg)
    for i, (key, label, detail) in enumerate(choices, 1):
        marker = f"{GREEN}*{RESET}" if key == default_key else " "
        print(f"  {marker} {BOLD}{i}{RESET}  {label}  {DIM}{detail}{RESET}")
    while True:
        raw = prompt(f"Choose 1–{len(choices)}", default_key)
        # Accept number or direct key
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                return choices[idx][0]
        for key, _, _ in choices:
            if raw.lower() == key.lower():
                return key
        print(f"  {RED}Invalid choice — try again.{RESET}")


def pick_grid() -> tuple[int, int]:
    section("Grid Size")
    presets = [
        ("1", "4 × 3  — Small   (12 cells)  ",  "good for quick tests"),
        ("2", "4 × 4  — Medium  (16 cells)  ",  "default — fits one full set"),
        ("3", "6 × 6  — Large   (36 cells)  ",  "multi-set sort"),
        ("4", "8 × 8  — XL      (64 cells)  ",  "big collection runs"),
        ("5", "Custom — enter rows and cols  ",  ""),
    ]
    for i, (_, label, detail) in enumerate(presets, 1):
        marker = f"{GREEN}*{RESET}" if i == 2 else " "
        print(f"  {marker} {BOLD}{i}{RESET}  {label}  {DIM}{detail}{RESET}")

    while True:
        raw = prompt("Choose 1–5", "2")
        if raw == "1": return (4, 3)
        if raw == "2": return (4, 4)
        if raw == "3": return (6, 6)
        if raw == "4": return (8, 8)
        if raw == "5":
            while True:
                try:
                    rows = int(prompt("  Rows", "4"))
                    cols = int(prompt("  Cols", "4"))
                    if rows >= 1 and cols >= 1:
                        return (rows, cols)
                    print(f"  {RED}Must be at least 1x1.{RESET}")
                except ValueError:
                    print(f"  {RED}Enter whole numbers only.{RESET}")
        print(f"  {RED}Invalid — enter 1 to 5.{RESET}")


def pick_cards(deck_size: int) -> int | None:
    section("Number of Cards to Sort")
    print(f"  {DIM}Deck has {deck_size} cards total.{RESET}")
    choices = [
        ("all",   f"All {deck_size} cards         ",   ""),
        ("half",  f"First {deck_size // 2} cards  ",   "half the deck"),
        ("10",    "First 10                       ",   "quick demo"),
        ("5",     "First 5                        ",   "fastest test"),
        ("custom","Custom number                  ",   ""),
    ]
    for i, (key, label, detail) in enumerate(choices, 1):
        marker = f"{GREEN}*{RESET}" if key == "all" else " "
        print(f"  {marker} {BOLD}{i}{RESET}  {label}  {DIM}{detail}{RESET}")
    while True:
        raw = prompt("Choose 1–5", "1")
        if raw == "1" or raw.lower() == "all": return None
        if raw == "2" or raw.lower() == "half": return deck_size // 2
        if raw == "3": return min(10, deck_size)
        if raw == "4": return min(5, deck_size)
        if raw == "5" or raw.lower() == "custom":
            while True:
                try:
                    n = int(prompt(f"  How many cards (1–{deck_size})", str(deck_size)))
                    if 1 <= n <= deck_size:
                        return n
                    print(f"  {RED}Must be between 1 and {deck_size}.{RESET}")
                except ValueError:
                    print(f"  {RED}Enter a whole number.{RESET}")
        print(f"  {RED}Invalid — enter 1 to 5.{RESET}")


def confirm_and_run(args: list[str]) -> None:
    header()
    section("Ready to Run")
    cmd = "python main.py " + " ".join(args)
    print(f"\n  Command:  {BOLD}{CYAN}{cmd}{RESET}\n")
    go = prompt("Press Enter to start, or type 'back' to change options", "go")
    if go.lower() == "back":
        return main_menu()
    print()
    subprocess.run([sys.executable, "main.py"] + args, cwd=os.path.dirname(os.path.abspath(__file__)))
    print(f"\n  {DIM}Press Enter to return to the menu...{RESET}")
    input()
    main_menu()


def show_help():
    header()
    section("All Available Options (CLI Reference)")
    rows = [
        ("--grid ROWSxCOLS",    "Grid dimensions",      "e.g.  --grid 4x4  or  --grid 6x6"),
        ("--strategy NAME",     "Sorting strategy",     "by_rarity_and_set | by_rarity | by_set | by_price"),
        ("--cards N",           "Limit card count",     "e.g.  --cards 10"),
        ("--no-viz",            "Headless mode",        "skip matplotlib, print to terminal only"),
        ("--log FILE.json",     "Export event log",     "saves pick/drop events as JSON"),
        ("--cnn-hook",          "Demo CNN hook",        "simulates live CNN data feed per card"),
    ]
    print()
    for flag, label, detail in rows:
        print(f"  {GREEN}{flag:<22}{RESET}  {label:<22}  {DIM}{detail}{RESET}")

    section("Sorting Strategies Explained")
    strats = [
        ("by_rarity_and_set", "Row = rarity tier, Col = set code  (BEST for FaB collection sorting)"),
        ("by_rarity",         "Row = rarity tier, columns fill left to right"),
        ("by_set",            "Col = set code (WTR/ARC/MON…), rows fill top to bottom"),
        ("by_price",          "Row 0 = $20+, Row 1 = $5-20, Row 2 = $1-5, Row 3 = $0-1"),
    ]
    for name, desc in strats:
        print(f"\n  {BOLD}{GREEN}{name}{RESET}")
        print(f"    {desc}")

    section("Grid Presets")
    presets = [
        ("4×3  (--grid 4x3)",  "12 cells — Small,  good for quick tests"),
        ("4×4  (--grid 4x4)",  "16 cells — Medium, default"),
        ("6×6  (--grid 6x6)",  "36 cells — Large,  multi-set collection"),
        ("8×8  (--grid 8x8)",  "64 cells — XL,     big runs"),
    ]
    for name, desc in presets:
        print(f"  {GREEN}{name:<22}{RESET}  {desc}")

    section("Rarity Tiers (Flesh and Blood)")
    rarities = [
        ("F  — Fabled",      "Row 0",  "#FFD700  gold"),
        ("L  — Legendary",   "Row 0",  "#9B59B6  purple"),
        ("CF — Cold Foil",   "Row 1",  "#C0C0C0  silver"),
        ("M  — Majestic",    "Row 1",  "#E67E22  orange"),
        ("S  — Super Rare",  "Row 1",  "#BDC3C7  light silver"),
        ("R  — Rare",        "Row 2",  "#3498DB  blue"),
        ("C  — Common",      "Row 3",  "#95A5A6  grey"),
        ("T  — Token",       "Row 3",  "#ECF0F1  white"),
    ]
    for code, row, colour in rarities:
        print(f"  {GREEN}{code:<22}{RESET}  {row:<8}  {DIM}{colour}{RESET}")

    print(f"\n  {DIM}Press Enter to return to the menu...{RESET}")
    input()
    main_menu()


def main_menu():
    header()
    section("Main Menu")
    option("1", "Quick Run          ", "4×4 grid, all cards, by_rarity_and_set (recommended start)")
    option("2", "Custom Run         ", "choose grid, strategy, card count, and options")
    option("3", "Headless / No GUI  ", "run without matplotlib — fastest, prints to terminal")
    option("4", "Show all options   ", "explain every flag, strategy, and rarity")
    option("5", "Exit               ", "")

    choice = prompt("Choose 1–5", "1")

    if choice == "1":
        confirm_and_run([])

    elif choice == "2":
        header()
        rows, cols = pick_grid()

        strategy = pick(
            "Sorting Strategy",
            [
                ("by_rarity_and_set", "By Rarity + Set    ", "row=rarity tier, col=set code  ← most useful"),
                ("by_rarity",         "By Rarity only     ", "row=rarity, columns fill left to right"),
                ("by_set",            "By Set only        ", "col=set code, rows fill top to bottom"),
                ("by_price",          "By Price           ", "row 0=$20+  row 1=$5-20  row 2=$1-5  row 3=<$1"),
            ],
            "by_rarity_and_set",
        )

        # Import deck here just to get its size for the prompt
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from main import SAMPLE_DECK
        max_cards = pick_cards(len(SAMPLE_DECK))

        viz_choice = pick(
            "Visualization",
            [
                ("yes",  "Matplotlib window  ", "animated gantry + grid — requires display"),
                ("no",   "Headless / text    ", "terminal output only — faster"),
            ],
            "yes",
        )

        cnn_choice = pick(
            "CNN Hook",
            [
                ("no",   "Off  ", "rule-based sorting only"),
                ("yes",  "On   ", "simulates live CNN data feed per card"),
            ],
            "no",
        )

        log_choice = pick(
            "Event Log",
            [
                ("no",      "None       ", "no log file"),
                ("yes",     "run.json   ", "export pick/drop events to run.json"),
            ],
            "no",
        )

        args = [f"--grid {rows}x{cols}", f"--strategy {strategy}"]
        if max_cards:
            args.append(f"--cards {max_cards}")
        if viz_choice == "no":
            args.append("--no-viz")
        if cnn_choice == "yes":
            args.append("--cnn-hook")
        if log_choice == "yes":
            args.append("--log run.json")

        confirm_and_run(args)

    elif choice == "3":
        header()
        rows, cols = pick_grid()
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from main import SAMPLE_DECK
        max_cards = pick_cards(len(SAMPLE_DECK))
        args = ["--no-viz", f"--grid {rows}x{cols}"]
        if max_cards:
            args.append(f"--cards {max_cards}")
        confirm_and_run(args)

    elif choice == "4":
        show_help()

    elif choice == "5":
        print(f"\n  {DIM}Goodbye.{RESET}\n")
        sys.exit(0)

    else:
        print(f"  {RED}Invalid choice — try again.{RESET}")
        main_menu()


if __name__ == "__main__":
    main_menu()
