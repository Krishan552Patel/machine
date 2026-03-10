# ---------------------------------------------------------------------------
# cnn_bridge.py  —  Scan a folder of card photos with the ML model and
#                   build an InputStack ready for the machine sorter.
#
# Photos can be named anything: photo1.jpg, IMG_001.png, card.webp, etc.
# The CNN identifies each card from the image content alone.
#
# Usage:
#   from cnn_bridge import scan_folder_to_stack
#   stack = scan_folder_to_stack(images_dir="C:/my/photos", model_path="...")
# ---------------------------------------------------------------------------
from __future__ import annotations

import sys
from pathlib import Path

# Allow importing card-recognition modules from the sibling folder
_CARD_REC_DIR = Path(__file__).resolve().parent.parent / "card-recognition"
if str(_CARD_REC_DIR) not in sys.path:
    sys.path.insert(0, str(_CARD_REC_DIR))

import config as machine_config  # machine/config.py

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def _map_result_to_cnn_dict(results: list[dict]) -> dict:
    """
    Convert inference.py identify() output → the CNN dict format that
    CardData.from_cnn_dict() expects.

    inference.py fields       →  machine sorter fields
    ─────────────────────────────────────────────────
    visual_confidence         →  confidence
    card_id / printing_uid   →  card_id
    name                     →  name
    set_id                   →  set_code
    rarity                   →  rarity
    types[0] (lowered)       →  class  (hero_class)
    —                        →  price_usd (0.0, unknown)
    top-k list               →  top_predictions [{label, score}]
    """
    if not results:
        return {
            "confidence": 0.0, "card_id": "UNKNOWN", "name": "Unknown",
            "set_code": "???", "rarity": machine_config.RARITY_COMMON,
            "class": "generic", "price_usd": 0.0, "top_predictions": [],
        }

    top = results[0]
    types = top.get("types") or []
    hero_class = types[0].lower() if types else "generic"

    return {
        "confidence":      top.get("visual_confidence", 0.0),
        "card_id":         top.get("card_id") or top.get("printing_unique_id", "UNKNOWN"),
        "name":            top.get("name", "Unknown"),
        "set_code":        top.get("set_id", "???"),
        "rarity":          top.get("rarity", machine_config.RARITY_COMMON),
        "class":           hero_class,
        "price_usd":       0.0,
        "top_predictions": [
            {"label": r.get("name", ""), "score": r.get("visual_confidence", 0.0)}
            for r in results
        ],
    }


def scan_folder_to_stack(
    images_dir: str,
    model_path: str,
    top_k: int = 5,
):
    """
    Scan all card photos in a folder, identify each with the ML model,
    and return a populated InputStack ready for simulation.

    Photos can be named anything — the CNN reads the image content to
    identify the card, not the filename.

    Args:
        images_dir:  Folder of card photos (any filenames).
        model_path:  Path to best_model.pth checkpoint.
        top_k:       How many candidates the model returns per photo.

    Returns:
        InputStack of CardData objects built from CNN identifications.
    """
    from inference import CardIdentifier  # card-recognition/inference.py
    from card import CardData, InputStack  # machine/card.py

    images_path = Path(images_dir)
    image_files = sorted(
        p for p in images_path.iterdir()
        if p.suffix.lower() in IMAGE_EXTENSIONS
    )

    if not image_files:
        print(f"[CNNBridge] No image files found in: {images_path}")
        return InputStack()

    print(f"\n[CNNBridge] Loading model from: {model_path}")
    identifier = CardIdentifier(model_path=model_path)

    print(f"\n[CNNBridge] Scanning {len(image_files)} photo(s) in: {images_path}")
    print("─" * 65)

    identified: list[CardData] = []
    low_confidence_count = 0

    for i, image_file in enumerate(image_files, start=1):
        results = identifier.identify(str(image_file), top_k=top_k)
        cnn_dict = _map_result_to_cnn_dict(results)
        card = CardData.from_cnn_dict(cnn_dict)

        conf = card.confidence
        threshold = machine_config.CNN_CONFIDENCE_THRESHOLD

        if conf < threshold:
            low_confidence_count += 1
            status = f"LOW CONFIDENCE → NEEDS REVIEW"
        else:
            status = f"{card.set_code} · {card.rarity_name}"

        print(
            f"  [{i}/{len(image_files)}] {image_file.name:<20}  "
            f"→  \"{card.name}\"  ({status} · conf={conf*100:.1f}%)"
        )
        if top_k > 1 and results:
            # Show runner-up for context
            alts = [
                f"{r['name']} ({r['visual_confidence']*100:.0f}%)"
                for r in results[1:3]
            ]
            if alts:
                print(f"              Alternatives: {', '.join(alts)}")

        identified.append(card)

    print("─" * 65)
    print(f"[CNNBridge] Identified: {len(identified)} card(s)  |  "
          f"Low confidence: {low_confidence_count}  |  "
          f"Threshold: {threshold*100:.0f}%\n")

    stack = InputStack()
    stack.load_from_list(identified)
    return stack
