"""Tests for the Project model: serialization round-trip, render plan, SRT."""
import json

from app.core.project import Project
from app.models.dialogue import DialogueLine, SpeakerProfile
from app.utils import import_export


def _sample_project() -> Project:
    p = Project(title="Lesson 1")
    p.speakers = [SpeakerProfile("Alex", "am_michael", 0.85),
                  SpeakerProfile("Mia", "af_heart", 1.0)]
    p.lines = [DialogueLine("Alex", "Hello Mia, how are you today?", pause_after=0.0),
               DialogueLine("Mia", "I am doing great, thanks for asking!", pause_after=0.0)]
    p.pause_between_lines = 0.4
    p.pause_between_speakers = 0.9
    return p


def test_roundtrip(tmp_path):
    p = _sample_project()
    path = tmp_path / "lesson.kstudio"
    p.save(path)
    assert path.suffix == ".kstudio"
    p2 = Project.load(path)
    assert p2.title == p.title
    assert len(p2.lines) == len(p.lines)
    assert p2.lines[0].speaker == "Alex"
    assert p2.lines[1].text == p.lines[1].text
    assert p2.speakers[0].voice_id == "am_michael"
    assert p2.pause_between_speakers == 0.9


def test_render_plan_skips_empty():
    p = _sample_project()
    p.lines.append(DialogueLine("Alex", "   "))
    plan = p.render_plan()
    assert len(plan) == 2
    assert plan[0]["voice_id"] == "am_michael"
    assert plan[1]["voice_id"] == "af_heart"
    assert plan[0]["speed"] == 0.85


def test_estimate_duration_positive():
    p = _sample_project()
    assert p.estimated_duration() > 0
    assert p.word_count >= 10


def test_srt_export(tmp_path):
    path = tmp_path / "out.srt"
    timed = [(0.0, 3.0, "Alex", "Hello how are you"),
             (3.5, 6.0, "Mia", "I'm great")]
    Project(title="x").export_srt(timed, path)
    text = path.read_text()
    assert "00:00:00,000 --> 00:00:03,000" in text
    assert "Alex: Hello how are you" in text
    blocks = text.split("\n\n")
    assert len(blocks) == 2


def test_import_txt_speaker_prefix():
    lines = import_export.parse_txt("Alex: Hello there\nMia: Hi!\nBare line")
    assert len(lines) == 3
    assert lines[0].speaker == "Alex"
    assert lines[2].speaker == "Speaker A"


def test_import_csv_and_json_roundtrip():
    p = _sample_project()
    csv_text = import_export.export_csv(p.lines)
    parsed = import_export.parse_csv(csv_text)
    assert [l.text for l in parsed] == [l.text for l in p.lines]

    json_text = import_export.export_json(p.lines)
    parsed = import_export.parse_json(json_text)
    assert parsed[0].speaker == "Alex"


def test_default_output_path(tmp_path):
    p = _sample_project()
    p.output_dir = ""
    out = p.default_output_path(ext="wav")
    assert out.name.startswith("Lesson")
    assert out.suffix == ".wav"
