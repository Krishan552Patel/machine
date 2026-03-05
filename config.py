# ---------------------------------------------------------------------------
# config.py  —  Hardware constants and machine configuration
# ---------------------------------------------------------------------------

# --- Stepper motor hardware ---
STEPS_PER_MM: float = 80.0        # steps per mm (both A and B motors)
MICROSTEPS: int = 16               # microstepping divisor on the driver
MAX_FEEDRATE_MM_S: float = 150.0   # maximum XY travel speed  (mm/s)
ACCELERATION_MM_S2: float = 500.0  # trapezoidal accel ramp    (mm/s²)

# --- Z axis ---
Z_TRAVEL_MM: float = 10.0          # distance head drops to pick/place (mm)
Z_SPEED_MM_S: float = 30.0         # Z axis speed (mm/s)
Z_ACCELERATION_MM_S2: float = 200.0

# --- Physical card dimensions (Flesh and Blood standard) ---
CARD_WIDTH_MM: float = 63.0
CARD_HEIGHT_MM: float = 88.0
CELL_PADDING_MM: float = 5.0       # gap between cards in the grid

# --- Grid dimensions ---
GRID_CELL_WIDTH_MM: float = CARD_WIDTH_MM + CELL_PADDING_MM    # 68 mm
GRID_CELL_HEIGHT_MM: float = CARD_HEIGHT_MM + CELL_PADDING_MM  # 93 mm

GRID_ROWS: int = 4
GRID_COLS: int = 4

# Grid origin — top-left corner of cell (0,0) in machine coordinates (mm)
GRID_ORIGIN_X_MM: float = 80.0
GRID_ORIGIN_Y_MM: float = 20.0

# --- Input stack position (machine coordinates, mm) ---
STACK_X_MM: float = 15.0
STACK_Y_MM: float = 15.0

# --- Simulation timing ---
# 0.0 = instant (no sleep), 1.0 = real-time, 0.1 = 10x fast
SIMULATION_TIME_SCALE: float = 0.0

# Interpolation resolution — smaller = more accurate but slower to compute
INTERPOLATION_STEP_MM: float = 1.0  # distance between interpolation ticks

# --- CNN integration ---
CNN_CONFIDENCE_THRESHOLD: float = 0.75   # cards below this -> NEEDS_REVIEW cell
NEEDS_REVIEW_CELL: tuple[int, int] = (0, GRID_COLS - 1)  # top-right corner

# --- Grid presets ---
GRID_PRESET_SMALL: tuple[int, int] = (4, 3)   # 12 cells
GRID_PRESET_MEDIUM: tuple[int, int] = (4, 4)  # 16 cells (default)
GRID_PRESET_LARGE: tuple[int, int] = (6, 6)   # 36 cells
GRID_PRESET_XL: tuple[int, int] = (8, 8)      # 64 cells

# --- Rarity codes (Flesh and Blood) ---
RARITY_FABLED = "F"
RARITY_LEGENDARY = "L"
RARITY_MAJESTIC = "M"
RARITY_SUPER_RARE = "S"
RARITY_RARE = "R"
RARITY_COMMON = "C"
RARITY_TOKEN = "T"
RARITY_COLD_FOIL = "CF"

# Rarity display names
RARITY_NAMES: dict[str, str] = {
    "F": "Fabled",
    "L": "Legendary",
    "M": "Majestic",
    "S": "Super Rare",
    "R": "Rare",
    "C": "Common",
    "T": "Token",
    "CF": "Cold Foil",
}

# --- Known FaB set codes (expandable) ---
FAB_SETS: list[str] = [
    "WTR",  # Welcome to Rathe
    "ARC",  # Arcane Rising
    "CRU",  # Crucible of War
    "MON",  # Monarch
    "EVO",  # Everfest
    "UPR",  # Uprising
    "DYN",  # Dynasty
    "OUT",  # Outsiders
    "HVY",  # Heavy Hitters
]
