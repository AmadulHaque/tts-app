"""Kokoro TTS engine wrapper.

The engine lazily imports kokoro (which pulls in torch) on first use, so the
GUI stays cheap to launch even before the model is ready. Device selection:

* ``mps``: used when the ``PYTORCH_ENABLE_MPS_FALLBACK=1`` env var is set and
  ``torch.backends.mps.is_available()``. main.py sets the env var early.
* ``cpu``: fallback.

A single KModel is shared across the American (``a``) and British (``b``)
pipelines. All synthesis happens under a lock: Kokoro inference is not
thread-safe, and preview + batch must never race the model.
"""

from __future__ import annotations

import os
import re
import threading
from typing import Callable, Iterable

import numpy as np

from ..models.voice import voice_info
from ..utils.logger import get_logger

log = get_logger("tts_engine")

DEFAULT_SR = 24000

# Kokoro quality/crash cliff: keep each pipeline call well under this size.
MAX_CHUNK_CHARS = 400

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+")


def split_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split *text* into sentence-bounded chunks of at most *max_chars*.

    Splits on sentence ends and newlines, packs sentences greedily, and hard
    splits pathological single sentences at word boundaries. Returns [] for
    blank input.
    """
    sentences: list[str] = []
    for bit in _SENTENCE_SPLIT.split(text or ""):
        bit = re.sub(r"\s+", " ", bit).strip(" -–—\"'“”‘’")
        if bit:
            sentences.append(bit)

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for sentence in sentences:
        if len(sentence) > max_chars:
            # Flush earlier sentences first to preserve order, then hard-split
            # the giant sentence at word boundaries.
            chunks.extend(_flush(current))
            current, current_len = [], 0
            while len(sentence) > max_chars:
                cut = sentence.rfind(" ", 0, max_chars)
                cut = cut if cut > max_chars // 2 else max_chars
                piece, sentence = sentence[:cut].strip(), sentence[cut:].strip()
                if piece:
                    chunks.append(piece)
            sentence = sentence.strip()
            if not sentence:
                continue
        if current_len + len(sentence) + (1 if current else 0) > max_chars:
            chunks.extend(_flush(current))
            current, current_len = [], 0
        current.append(sentence)
        current_len += len(sentence) + 1
    chunks.extend(_flush(current))
    return [c for c in chunks if c]


def _flush(packed: list[str]) -> list[str]:
    text = " ".join(packed).strip()
    packed.clear()
    return [text] if text else []


class TTSEngine:
    def __init__(self, model_repo_id: str = "hexgrad/Kokoro-82M", device: str = "auto",
                 progress_cb: Callable[[str], None] | None = None,
                 model_ready_cb: Callable[[], None] | None = None):
        self._repo_id = model_repo_id
        self._device_request = device
        self._progress_cb = progress_cb or (lambda _msg: None)
        self._model_ready_cb = model_ready_cb

        self._model = None          # KModel
        self._pipelines: dict[str, object] = {}   # lang_code -> KPipeline
        self._lock = threading.Lock()
        self._ready = False
        self._error: str | None = None
        self.voices: set[str] = set()   # voice ids known to kokoro

    # -- lifecycle ---------------------------------------------------------

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def device(self) -> str:
        return self._resolve_device()

    def initialize(self) -> None:
        """Load the model + language pipelines. Idempotent; safe to call from
        a background thread. Downloads weights from HF on first run."""
        with self._lock:
            if self._ready:
                return
            self._progress_cb("Loading Kokoro model…")
            try:
                import torch  # noqa: F401  (ensure available early)
                from kokoro import KModel, KPipeline
            except Exception as e:  # noqa: BLE001
                self._error = f"Kokoro not installed correctly: {e}"
                log.error(self._error)
                self._progress_cb(self._error)
                raise RuntimeError(self._error) from e

            try:
                device = self._resolve_device()
                self._progress_cb(f"Loading Kokoro model on {device.upper()}…")

                model = KModel(repo_id=self._repo_id).to(device).eval()
                # Share one model across both English language pipelines.
                a = KPipeline(lang_code="a", model=model, repo_id=self._repo_id)
                b = KPipeline(lang_code="b", model=model, repo_id=self._repo_id)
                self._model = model
                self._pipelines = {"a": a, "b": b}

                # Union of voice names known to kokoro (lazy-triggered on demand,
                # so this only reflects built-in voices, not downloads).
                self.voices = set(a.voices).union(b.voices)
                self._ready = True
                self._error = None
                log.info("Kokoro engine ready on %s (%d voices)", device, len(self.voices))
                self._progress_cb(f"Ready on {device.upper()}")
                if self._model_ready_cb:
                    self._model_ready_cb()
            except Exception as e:  # noqa: BLE001
                self._error = f"Failed to load Kokoro: {e}"
                log.exception(self._error)
                self._progress_cb(self._error)
                raise RuntimeError(self._error) from e

    # -- synthesis --------------------------------------------------------

    def synthesize(self, text: str, voice_id: str, speed: float = 1.0,
                   cancel_event: threading.Event | None = None,
                   on_chunk: Callable[[int, int], None] | None = None) -> np.ndarray:
        """Synthesize *text* with *voice_id* at *speed*.

        Long input is first split into sentence-bounded chunks (Kokoro degrades
        past a few hundred characters per call). Returns mono float32 samples
        at 24000 Hz. ``on_chunk(chunk_i, total)`` is called per chunk;
        ``cancel_event`` is checked between chunks and raises
        ``InterruptedError`` when set.
        """
        if not self._ready:
            self.initialize()

        voice_id, lang = self._resolve_voice(voice_id)

        pieces = split_text(text)
        if not pieces:
            raise ValueError("Nothing to synthesize — text is empty")
        total = len(pieces)
        speed = max(0.5, min(2.0, float(speed)))

        chunks: list[np.ndarray] = []
        with self._lock:  # single inference at a time
            pipeline = self._pipelines[lang]
            try:
                for index, piece in enumerate(pieces):
                    if cancel_event is not None and cancel_event.is_set():
                        raise InterruptedError("Generation cancelled")
                    generator = pipeline(piece, voice=voice_id, speed=speed,
                                         split_pattern=r"\n+")
                    for _gs, _ps, audio in generator:
                        if cancel_event is not None and cancel_event.is_set():
                            raise InterruptedError("Generation cancelled")
                        if audio is not None:
                            chunks.append(np.asarray(audio, dtype=np.float32).reshape(-1))
                    if on_chunk:
                        on_chunk(index, total)
            except InterruptedError:
                raise
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(f"Synthesis failed on chunk {index + 1}/{total}: {e}") from e

        if not chunks:
            raise RuntimeError("Synthesis produced no audio")
        return np.concatenate(chunks)


    def prefetch_voices(self, voice_ids: Iterable[str]) -> int:
        """Pre-download voice tensors (for the Voice Library). Non-blocking per
        voice; called from a worker thread."""
        if not self._ready:
            self.initialize()
        count = 0
        with self._lock:
            for vid in voice_ids:
                vid, lang = self._resolve_voice(vid)
                try:
                    self._pipelines[lang].voices[vid]  # lazy download/load
                    count += 1
                except Exception as e:  # noqa: BLE001
                    log.warning("Could not prefetch voice %s: %s", vid, e)
        return count


    # -- helpers ----------------------------------------------------------

    def voice_available(self, voice_id: str) -> bool:
        vid = voice_id.lower()
        return vid in self.voices if self.voices else True


    def _resolve_voice(self, voice_id: str) -> tuple[str, str]:
        vid = voice_id.lower()
        lang = "b" if vid.startswith("b") else "a"
        info = voice_info(vid)
        if info is not None:
            lang = info.lang_code
        return vid, lang


    def _resolve_device(self) -> str:
        req = (self._device_request or "auto").lower()
        if req == "cpu":
            return "cpu"
        fallback = os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") == "1"
        if req in ("auto", "mps") and fallback:
            try:
                import torch
                if torch.backends.mps.is_available():
                    return "mps"
            except Exception:  # noqa: BLE001
                pass
        return "cpu"


# Module-level singleton used across the app.
_engine: TTSEngine | None = None


def get_engine(**kwargs) -> TTSEngine:
    global _engine
    if _engine is None:
        _engine = TTSEngine(**kwargs)
    return _engine


def set_engine(engine: TTSEngine | None) -> None:
    global _engine
    _engine = engine
