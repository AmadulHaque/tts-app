"""Tests for engine text chunking (long paragraphs must split for Kokoro)."""

import pytest

from app.core.tts_engine import MAX_CHUNK_CHARS, split_text

INTRO = (
    "Hello, everyone. Welcome back to Speak Up Sessions English podcast. "
    "I'm Masu, your English teacher and friend, and I'm so happy you're here "
    "today. This is a very special video because today is day one of our "
    "30-day English fluency challenge. For the next 30 days, we're going to "
    "practice real English conversation together every single day. And by the "
    "end of this challenge, you will speak English more easily, more "
    "confidently, and more naturally. Today, you're going to learn and "
    "practice 99 sentences. Yes, 99. But don't worry, we'll do it "
    "step-by-step together. And joining me today is my friend Fizu."
)


def test_long_paragraph_splits_into_bounded_chunks():
    chunks = split_text(INTRO)
    assert len(chunks) > 1
    assert all(len(c) <= MAX_CHUNK_CHARS for c in chunks)
    # No words lost or reordered.
    assert " ".join(" ".join(chunks).split()) == " ".join(INTRO.split())


def test_short_text_unsplit():
    assert split_text("Hi there!") == ["Hi there!"]


def test_blank_text_gives_no_chunks():
    assert split_text("   \n  ") == []


def test_giant_sentence_hard_splits_in_order():
    words = [f"word{i}" for i in range(300)]
    chunks = split_text(" ".join(words) + ".")
    assert len(chunks) > 1
    assert all(len(c) <= MAX_CHUNK_CHARS for c in chunks)
    assert " ".join(" ".join(chunks).split()) == " ".join(words) + "."


def test_synthesize_rejects_empty():
    from app.core.tts_engine import TTSEngine

    engine = TTSEngine.__new__(TTSEngine)  # no model needed: validation first
    engine._ready = True
    with pytest.raises(ValueError):
        engine.synthesize("   ", "af_heart")
