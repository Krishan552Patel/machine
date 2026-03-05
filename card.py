# ---------------------------------------------------------------------------
# card.py  —  Flesh and Blood CardData model + InputStack
# ---------------------------------------------------------------------------
from __future__ import annotations
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import config


class StackEmptyError(Exception):
    """Raised when trying to pop from an empty InputStack."""


@dataclass
class CardData:
    """
    Represents a single Flesh and Blood trading card.

    Fields map directly to what the CNN will output.
    `raw_cnn_output` carries the unmodified model payload so that
    CNNSorter can access logits, top-k predictions, etc.
    """
    card_id: str                        # e.g. "WTR001"
    name: str                           # e.g. "Dorinthea Ironsong"
    set_code: str                       # e.g. "WTR", "MON"
    rarity: str                         # see config.RARITY_* constants
    hero_class: str                     # "warrior", "ninja", "wizard", "generic", etc.
    price_usd: float = 0.0             # market price
    confidence: float = 1.0            # CNN confidence score 0.0–1.0
    raw_cnn_output: dict[str, Any] | None = field(default=None, repr=False)

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict) -> "CardData":
        """Build a CardData from a plain dict (e.g. loaded from JSON)."""
        return cls(
            card_id=data.get("card_id", str(uuid.uuid4())[:8]),
            name=data.get("name", "Unknown"),
            set_code=data.get("set_code", "???"),
            rarity=data.get("rarity", config.RARITY_COMMON),
            hero_class=data.get("hero_class", "generic"),
            price_usd=float(data.get("price_usd", 0.0)),
            confidence=float(data.get("confidence", 1.0)),
            raw_cnn_output=data.get("raw_cnn_output", None),
        )

    @classmethod
    def from_cnn_dict(cls, cnn_output: dict) -> "CardData":
        """
        Build a CardData directly from a CNN model output dict.

        Expected CNN output format:
        {
            "card_id": "WTR001",
            "name": "Dorinthea Ironsong",
            "set_code": "WTR",
            "rarity": "L",
            "class": "warrior",
            "price_usd": 45.50,
            "confidence": 0.97,
            "top_predictions": [
                {"label": "Dorinthea Ironsong", "score": 0.97},
                {"label": "Ira, Crimson Haze",  "score": 0.02}
            ]
        }
        """
        card = cls(
            card_id=cnn_output.get("card_id", str(uuid.uuid4())[:8]),
            name=cnn_output.get("name", "Unknown"),
            set_code=cnn_output.get("set_code", "???"),
            rarity=cnn_output.get("rarity", config.RARITY_COMMON),
            hero_class=cnn_output.get("class", "generic"),
            price_usd=float(cnn_output.get("price_usd", 0.0)),
            confidence=float(cnn_output.get("confidence", 1.0)),
            raw_cnn_output=cnn_output,
        )
        return card

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "card_id": self.card_id,
            "name": self.name,
            "set_code": self.set_code,
            "rarity": self.rarity,
            "rarity_name": config.RARITY_NAMES.get(self.rarity, self.rarity),
            "hero_class": self.hero_class,
            "price_usd": self.price_usd,
            "confidence": self.confidence,
        }

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    @property
    def rarity_name(self) -> str:
        return config.RARITY_NAMES.get(self.rarity, self.rarity)

    @property
    def short_name(self) -> str:
        """Abbreviated name for grid display (max 8 chars)."""
        return self.name[:8] if len(self.name) > 8 else self.name

    def __str__(self) -> str:
        return (
            f"{self.card_id} \"{self.name}\" "
            f"[{self.rarity_name}] {self.set_code} ${self.price_usd:.2f}"
        )


# ---------------------------------------------------------------------------
# InputStack  —  the physical pile of cards to be sorted
# ---------------------------------------------------------------------------

class InputStack:
    """
    A LIFO stack representing the physical card pile.

    Index -1 = top of stack (next to be picked).
    Index  0 = bottom of stack.
    """

    def __init__(self, cards: list[CardData] | None = None) -> None:
        self._cards: list[CardData] = list(cards) if cards else []

    # ------------------------------------------------------------------
    # Stack operations
    # ------------------------------------------------------------------

    def push(self, card: CardData) -> None:
        """Place a card on top of the stack."""
        self._cards.append(card)

    def pop(self) -> CardData:
        """Remove and return the top card. Raises StackEmptyError if empty."""
        if not self._cards:
            raise StackEmptyError("Cannot pop from an empty stack.")
        return self._cards.pop()

    def peek(self) -> CardData | None:
        """Return the top card without removing it."""
        return self._cards[-1] if self._cards else None

    def is_empty(self) -> bool:
        return len(self._cards) == 0

    def remaining(self) -> int:
        return len(self._cards)

    # ------------------------------------------------------------------
    # Bulk loading
    # ------------------------------------------------------------------

    def load_from_list(self, cards: list[CardData]) -> None:
        """Replace stack contents (index 0 = bottom, last = top)."""
        self._cards = list(cards)

    def load_from_json(self, filepath: str) -> None:
        """Load cards from a JSON file (list of card dicts)."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._cards = [CardData.from_dict(d) for d in data]

    def load_from_cnn_json(self, filepath: str) -> None:
        """Load cards from a JSON file containing CNN output dicts."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._cards = [CardData.from_cnn_dict(d) for d in data]

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._cards)

    def __repr__(self) -> str:
        return f"InputStack({len(self._cards)} cards)"

    def preview(self, n: int = 5) -> str:
        """Show the top n cards for debugging."""
        top = self._cards[-(n):][::-1]
        lines = [f"  [{i}] {c}" for i, c in enumerate(top)]
        return "InputStack (top first):\n" + "\n".join(lines)
