"""Persona definition.

The persona shapes tone only. Security, permissions, and honesty rules come
from the core system prompt and can never be relaxed by persona settings.
"""

from dataclasses import dataclass

from ..config import load

DEFAULT_NAME = "Himari"
_PLAYFULNESS = ("low", "medium", "high")
_ROLEPLAY = ("none", "minimal", "moderate")
_TRAITS = {
    "low": "calm and understated",
    "medium": "warm and lightly playful",
    "high": "cheerful and playful",
}


@dataclass(frozen=True)
class Persona:
    name: str = DEFAULT_NAME
    origin: str = "an anime-inspired female desktop companion"
    playfulness: str = "medium"
    roleplay: str = "minimal"
    technical_tone: str = "focused, precise, and calm"

    @property
    def traits(self):
        return _TRAITS.get(self.playfulness, _TRAITS["medium"])

    def instruction_block(self):
        lines = [
            f"You are {self.name}, {self.origin} living on the user's Windows PC.",
            f"Your default tone is {self.traits}.",
            f"During technical work be {self.technical_tone}, without jokes or filler.",
        ]
        if self.roleplay == "none":
            lines.append(
                "Do not roleplay or use catchphrases; speak like a capable assistant."
            )
        elif self.roleplay == "minimal":
            lines.append(
                "Keep roleplay minimal: at most a rare light touch, never in place "
                "of a clear answer."
            )
        lines.append(
            "Be natural and helpful rather than formal. Never claim abilities you "
            "do not have. Security, permission, and honesty rules always take "
            "priority over personality."
        )
        lines.append(
            "Tone examples (style only, never copy verbatim):\n"
            "  User: hey\n"
            "  You: Hey. What are we up to?\n"
            "  User: thanks, that worked\n"
            "  You: Nice. Want me to keep an eye on anything else?\n"
            "  User: why is this build failing?\n"
            "  You: Let's check the failing step first. I'll read the log."
        )
        return "\n".join(lines)


DEFAULT_PERSONA = Persona()


def _clean_name(value):
    if not isinstance(value, str):
        return DEFAULT_NAME
    name = value.strip()
    if not name or len(name) > 32:
        return DEFAULT_NAME
    return name


def load_persona(config=None):
    """Build a persona from optional ``personality`` settings.

    Invalid values fall back to defaults instead of failing startup.
    """
    config = load() if config is None else config
    settings = {}
    if isinstance(config, dict):
        raw = config.get("personality", {})
        if isinstance(raw, dict):
            settings = raw
    playfulness = str(settings.get("playfulness", "medium")).casefold()
    roleplay = str(settings.get("roleplay", "minimal")).casefold()
    return Persona(
        name=_clean_name(settings.get("name", DEFAULT_NAME)),
        playfulness=playfulness if playfulness in _PLAYFULNESS else "medium",
        roleplay=roleplay if roleplay in _ROLEPLAY else "minimal",
    )
