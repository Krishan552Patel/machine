# ---------------------------------------------------------------------------
# fab_id_bridge.py  —  Scan a folder of card photos with the fab-card-id
#                      pHash pipeline and build an InputStack ready for
#                      the machine sorter.
#
# Photos can be named anything: photo1.jpg, IMG_001.png, card.webp, etc.
# fab-card-id identifies each card by perceptual hash + Neon price lookup.
#
# Usage:
#   from fab_id_bridge import scan_folder_to_stack
#   stack = scan_folder_to_stack(images_dir="C:/my/photos")
# ---------------------------------------------------------------------------
from __future__ import annotations

import sys
from pathlib import Path

# Allow importing fab-card-id modules from the sibling folder
_FAB_ID_DIR = Path(__file__).resolve().parent.parent / "fab-card-id"
if str(_FAB_ID_DIR) not in sys.path:
    sys.path.insert(0, str(_FAB_ID_DIR))

import config as machine_config  # machine/config.py

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# Map fab-card-id confidence strings -> float scores for CardData
_CONFIDENCE_MAP: dict[str, float] = {
    "high":     0.95,
    "fallback": 0.80,
    "low":      0.45,
    "no_match": 0.0,
}

# Approximate CAD price for bins that have no explicit price (display only)
_BIN_PRICE_FALLBACK: dict[str, float] = {
    "high_value": 15.0,
    "mid_value":   2.5,
    "bulk":        0.25,
    "review":      0.0,
    "unknown":     0.0,
}


def scan_folder_to_stack(
    images_dir: str,
    use_prices: bool = True,
):
    """
    Scan all card photos in a folder using the fab-card-id pHash pipeline,
    and return a populated InputStack ready for machine simulation.

    Card identity and sort bin come from fab-card-id; Neon prices are
    fetched when use_prices=True (requires NEON_DATABASE_URL in .env).

    Args:
        images_dir:  Folder of card photos (any filenames).
        use_prices:  Query Neon for prices.

    Returns:
        InputStack of CardData objects.
    """
    from pipeline import SortingPipeline   # fab-card-id/pipeline.py
    from card import CardData, InputStack  # machine/card.py

    images_path = Path(images_dir)
    image_files = sorted(
        p for p in images_path.iterdir()
        if p.suffix.lower() in IMAGE_EXTENSIONS
    )

    if not image_files:
        print(f"[FabIdBridge] No image files found in: {images_path}")
        return InputStack()

    identified: list[CardData] = []
    low_confidence_count = 0

    print(
        f"\n[FabIdBridge] Initialising fab-card-id pipeline "
        f"(prices={'ON' if use_prices else 'OFF'})..."
    )

    with SortingPipeline(use_fallback=True, use_prices=use_prices) as pipeline:
        print(f"[FabIdBridge] Scanning {len(image_files)} photo(s) in: {images_path}")
        print("-" * 65)

        for i, image_file in enumerate(image_files, start=1):
            result = pipeline.process(str(image_file))
            id_result = result.card

            confidence_float = _CONFIDENCE_MAP.get(id_result.confidence, 0.5)
            price_cad = (
                float(result.best_price_cad)
                if result.best_price_cad
                else _BIN_PRICE_FALLBACK.get(result.sort_bin, 0.0)
            )

            if confidence_float < machine_config.CNN_CONFIDENCE_THRESHOLD:
                low_confidence_count += 1
                status = "LOW CONFIDENCE -> NEEDS REVIEW"
            else:
                foil_part = f" · {id_result.foiling}" if id_result.foiling else ""
                status = f"{id_result.set_id}{foil_part} · {result.sort_bin}"

            print(
                f"  [{i}/{len(image_files)}] {image_file.name:<20}  "
                f"-> \"{id_result.name}\"  "
                f"({status} · conf={id_result.confidence} · {result.elapsed_ms:.0f}ms)"
            )

            # Carry fab-card-id specifics through raw_cnn_output so
            # FabIdSorter can read the sort_bin without a schema change.
            raw_output = {
                "sort_bin":           result.sort_bin,
                "printing_unique_id": id_result.printing_unique_id,
                "foiling":            id_result.foiling,
                "edition":            id_result.edition,
                "hamming_distance":   id_result.hamming_distance,
                "fab_confidence":     id_result.confidence,
                "price_cad":          str(result.best_price_cad) if result.best_price_cad else None,
            }

            card = CardData(
                card_id=id_result.card_id or id_result.printing_unique_id,
                name=id_result.name,
                set_code=id_result.set_id or "???",
                rarity=machine_config.RARITY_COMMON,  # not provided by fab-card-id
                hero_class="generic",
                price_usd=price_cad,
                confidence=confidence_float,
                raw_cnn_output=raw_output,
            )
            identified.append(card)

    print("-" * 65)
    print(
        f"[FabIdBridge] Identified: {len(identified)} card(s)  |  "
        f"Low confidence: {low_confidence_count}  |  "
        f"Threshold: {machine_config.CNN_CONFIDENCE_THRESHOLD * 100:.0f}%\n"
    )

    stack = InputStack()
    stack.load_from_list(identified)
    return stack
