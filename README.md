# machine

CoreXY gantry simulation and card sorting system for Flesh and Blood trading cards. Simulates stepper motor movement, grid cell assignment, and card identification via pluggable sorter strategies.

---

## How it works

1. An **InputStack** of cards is loaded (from sample data, CNN model, or fab-card-id)
2. The **Gantry** simulates CoreXY stepper motor movement to pick and place each card
3. A **Sorter** assigns each card to a grid cell based on the chosen strategy
4. An optional **Visualizer** renders the grid state in real time via matplotlib

---

## Setup

```bash
pip install -r requirements.txt   # numpy, matplotlib, pillow, etc.
```

---

## Usage

### Sample deck (no photos needed)

```bash
python main.py
python main.py --grid 6x6 --strategy by_price
python main.py --no-viz          # headless, text output only
python main.py --copies 2        # 2 copies of each card
```

### Real cards — fab-card-id (pHash + prices) — recommended

Identify cards using perceptual hashing + Neon price lookup. Requires the `fab-card-id` sibling folder to be set up (see its README).

```bash
python main.py --use-fab-id --images-dir path/to/photos/

# Offline (no Neon price lookup)
python main.py --use-fab-id --images-dir path/to/photos/ --no-prices
```

Sort bins with this mode:

| Grid row | Bin | Price |
|---|---|---|
| Row 0 | high_value | ≥ CA$10 |
| Row 1 | mid_value | CA$1–$10 |
| Row 2 | bulk | < CA$1 |
| Top-right cell | review / unknown | Low confidence or no match |

### Real cards — CNN model

Identify cards using the trained neural network from `card-recognition`.

```bash
python main.py --use-cnn --images-dir path/to/photos/
python main.py --use-cnn --images-dir path/to/photos/ --model-path path/to/best_model.pth
```

---

## Sorting strategies (sample deck / CNN mode)

| Strategy | Description |
|---|---|
| `by_rarity_and_set` | Row = rarity tier, col = set code (default) |
| `by_rarity` | Row = rarity tier, fill left to right |
| `by_set` | Col = set code, fill top to bottom |
| `by_price` | Row = price tier ($0-1 / $1-5 / $5-20 / $20+) |

```bash
python main.py --strategy by_price
```

---

## All flags

| Flag | Description |
|---|---|
| `--grid ROWSxCOLS` | Grid size, e.g. `4x4`, `6x6` (default: `4x4`) |
| `--strategy NAME` | Sorting strategy (see above) |
| `--no-viz` | Disable matplotlib visualizer |
| `--cards N` | Process only the first N cards |
| `--copies N` | Repeat each card N times in the stack |
| `--log FILE` | Export event log to JSON |
| `--use-fab-id` | Use fab-card-id pHash pipeline (requires `--images-dir`) |
| `--use-cnn` | Use CNN model (requires `--images-dir`) |
| `--no-prices` | Skip Neon price lookup when using `--use-fab-id` |
| `--images-dir PATH` | Folder of card photos |
| `--model-path PATH` | Path to CNN checkpoint (default: `../card-recognition/model/checkpoints/best_model.pth`) |
| `--cnn-hook` | Enable demo CNN hook in sample deck mode |

---

## File overview

| File | Purpose |
|---|---|
| `config.py` | Hardware constants, grid settings, rarity codes |
| `card.py` | `CardData` dataclass + `InputStack` |
| `grid.py` | `CardGrid` — cell placement and overflow logic |
| `gantry.py` | CoreXY kinematics + stepper motor simulation |
| `motor.py` | `StepperMotor` — trapezoidal acceleration model |
| `sorter.py` | `FaBRuleBasedSorter`, `FabIdSorter`, `CNNSorter` |
| `simulation.py` | Orchestrates gantry + stack + sorter loop |
| `visualizer.py` | Matplotlib real-time grid visualizer |
| `fab_id_bridge.py` | Connects fab-card-id pipeline to machine InputStack |
| `cnn_bridge.py` | Connects card-recognition CNN to machine InputStack |
| `main.py` | CLI entry point |

---

## Related repos

| Repo | Role |
|---|---|
| `fab-card-id` | pHash card identification + Neon price lookup |
| `card-recognition` | CNN model for card identification |
| `price-compare` | Web app for price tracking and collection management |
