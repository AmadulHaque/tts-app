"""Voice catalog and voice metadata for the English voices of Kokoro-82M.

Data sourced from hexgrad/Kokoro-82M VOICES.md. Only the American and
British English voices are catalogued (the app targets English podcast
conversations). Grade is the library's overall training-quality estimate.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class VoiceInfo:
    voice_id: str
    name: str
    gender: str          # "male" | "female"
    accent: str          # "US" | "UK"
    lang_code: str       # "a" (American) | "b" (British)
    grade: str           # overall quality estimate, e.g. "A-", "C+"
    description: str


# voice_id -> display-friendly name
_VOICE_NAMES = {
    "af_heart": "Heart",
    "af_alloy": "Alloy",
    "af_aoede": "Aoede",
    "af_bella": "Bella",
    "af_jessica": "Jessica",
    "af_kore": "Kore",
    "af_nicole": "Nicole",
    "af_nova": "Nova",
    "af_river": "River",
    "af_sarah": "Sarah",
    "af_sky": "Sky",
    "am_adam": "Adam",
    "am_echo": "Echo",
    "am_eric": "Eric",
    "am_fenrir": "Fenrir",
    "am_liam": "Liam",
    "am_michael": "Michael",
    "am_onyx": "Onyx",
    "am_puck": "Puck",
    "am_santa": "Santa",
    "bf_alice": "Alice",
    "bf_emma": "Emma",
    "bf_isabella": "Isabella",
    "bf_lily": "Lily",
    "bm_daniel": "Daniel",
    "bm_fable": "Fable",
    "bm_george": "George",
    "bm_lewis": "Lewis",
}

# voice_id -> (gender, accent, grade, description). Descriptions are short
# subjective traits; keep them terse for the UI grid.
_VOICE_META: dict[str, tuple[str, str, str, str]] = {
    # --- American English ---
    "af_heart":  ("female", "US", "A",   "Warm, expressive, standout default"),
    "af_alloy":  ("female", "US", "C",   "Neutral and steady"),
    "af_aoede":  ("female", "US", "C+",  "Clear, rounded"),
    "af_bella":  ("female", "US", "A-",  "Lively and versatile"),
    "af_jessica":("female", "US", "D",   "Soft-spoken"),
    "af_kore":   ("female", "US", "C+",  "Bright, articulate"),
    "af_nicole": ("female", "US", "B-",  "Calm, studio-quality"),
    "af_nova":   ("female", "US", "C",   "Energetic, upbeat"),
    "af_river":  ("female", "US", "D",   "Smooth, laid-back"),
    "af_sarah":  ("female", "US", "C+",  "Friendly, conversational"),
    "af_sky":    ("female", "US", "C-",  "Airy, youthful"),
    "am_adam":   ("male", "US", "F+",   "Deep, gravelly"),
    "am_echo":   ("male", "US", "D",    "Neutral, even"),
    "am_eric":   ("male", "US", "D",    "Warm and even"),
    "am_fenrir": ("male", "US", "C+",   "Low, rich baritone"),
    "am_liam":   ("male", "US", "D",    "Light, friendly"),
    "am_michael":("male", "US", "C+",   "Neutral newscaster"),
    "am_onyx":   ("male", "US", "D",    "Deep, resonant"),
    "am_puck":   ("male", "US", "C+",   "Energetic, lively"),
    "am_santa":  ("male", "US", "D-",   "Jolly, deep"),
    # --- British English ---
    "bf_alice":  ("female", "UK", "D",  "Soft, gentle"),
    "bf_emma":   ("female", "UK", "B-", "Warm, friendly"),
    "bf_isabella":("female", "UK", "C", "Bright, clear"),
    "bf_lily":   ("female", "UK", "D",  "Gentle, light"),
    "bm_daniel": ("male", "UK", "D",    "Neutral, steady"),
    "bm_fable":  ("male", "UK", "C",    "Calm, storytelling"),
    "bm_george": ("male", "UK", "C",    "Warm, measured"),
    "bm_lewis":  ("male", "UK", "D+",   "Reserved, deep"),
}


def _lang_for(voice_id: str) -> str:
    return "b" if voice_id.startswith("b") else "a"


def _build_catalog() -> dict[str, VoiceInfo]:
    catalog: dict[str, VoiceInfo] = {}
    for vid in _VOICE_META:
        gender, accent, grade, desc = _VOICE_META[vid]
        catalog[vid] = VoiceInfo(
            voice_id=vid,
            name=_VOICE_NAMES.get(vid, vid),
            gender=gender,
            accent=accent,
            lang_code=_lang_for(vid),
            grade=grade,
            description=desc,
        )
    return catalog


VOICE_CATALOG: dict[str, VoiceInfo] = _build_catalog()

ENGLISH_VOICE_IDS: tuple[str, ...] = tuple(sorted(VOICE_CATALOG))

# Grouped for convenience in the UI.
US_FEMALE = [v for v in VOICE_CATALOG.values() if v.accent == "US" and v.gender == "female"]
US_MALE = [v for v in VOICE_CATALOG.values() if v.accent == "US" and v.gender == "male"]
UK_FEMALE = [v for v in VOICE_CATALOG.values() if v.accent == "UK" and v.gender == "female"]
UK_MALE = [v for v in VOICE_CATALOG.values() if v.accent == "UK" and v.gender == "male"]


def voice_info(voice_id: str) -> VoiceInfo | None:
    return VOICE_CATALOG.get(voice_id)


def voice_to_dict(v: VoiceInfo) -> dict:
    return asdict(v)
