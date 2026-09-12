"""Tests for the embedded voice catalog (must stay a clean, complete English set)."""

from app.models.voice import VOICE_CATALOG, ENGLISH_VOICE_IDS, voice_info


def test_exactly_28_english_voices():
    assert len(VOICE_CATALOG) == 28


def test_no_duplicate_ids():
    assert len(set(ENGLISH_VOICE_IDS)) == len(ENGLISH_VOICE_IDS)


def test_all_entries_complete():
    expected = {"voice_id", "name", "gender", "accent", "lang_code", "grade", "description"}
    for v in VOICE_CATALOG.values():
        info = voice_info(v.voice_id)
        assert info is not None
        d = vars(info)
        assert expected <= set(d.keys())
        assert d["gender"] in ("male", "female")
        assert d["accent"] in ("US", "UK")


def test_gender_distribution():
    genders = [v.gender for v in VOICE_CATALOG.values()]
    assert genders.count("female") == 15   # 11 US + 4 UK
    assert genders.count("male") == 13     # 9 US + 4 UK


def test_premium_voices_present():
    for vid in ("af_heart", "af_bella", "am_michael", "bm_fable", "bf_emma"):
        assert vid in VOICE_CATALOG


def test_lang_codes():
    for v in VOICE_CATALOG.values():
        assert v.lang_code == ("b" if v.voice_id.startswith("b") else "a")
