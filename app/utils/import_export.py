"""Import/export of dialogue scripts between .txt, .json, .csv and .srt.

Import targets a list of raw lines::

    ("Alex", "Hello, how are you?", 0.0, None, None)

Export produces file content. SRT export needs concrete line timings.
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

from ..models.dialogue import DialogueLine


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

_SPEAKER_RE = re.compile(r"^\s*(?:\[([^\]]+)\]|\s*([A-Za-z][A-Za-z0-9 _-]{0,19})\s*[:|])\s*(.+)$")


def parse_txt(text: str, default_speaker: str = "Speaker A") -> list[DialogueLine]:
    """Parse plain text. Supported line shapes:
      - ``Speaker: text`` / ``Speaker|text``  (speaker prefix)
      - bare text  -> default_speaker
      Blank lines are skipped."""
    lines: list[DialogueLine] = []
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        m = _SPEAKER_RE.match(line)
        if m:
            speaker = (m.group(1) or m.group(2)).strip().title()
            body = m.group(3).strip()
        else:
            speaker, body = default_speaker, line.strip()
        if body:
            lines.append(DialogueLine(speaker=speaker, text=body))
    return lines


def parse_csv(text: str) -> list[DialogueLine]:
    rows = list(csv.reader(io.StringIO(text)))
    lines: list[DialogueLine] = []
    for i, row in enumerate(rows):
        if i == 0 and row and row[0].strip().lower() in ("speaker", "speaker name"):
            continue  # header
        if not row:
            continue
        speaker = (row[0] or "Speaker A").strip() if row else "Speaker A"
        body = row[1].strip() if len(row) > 1 else ""
        pause = float(row[2]) if len(row) > 2 and row[2].strip() else 0.0
        if body:
            lines.append(DialogueLine(speaker=speaker, text=body, pause_after=pause))
    return lines


def parse_json(text: str) -> list[DialogueLine]:
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("lines", [])
    lines: list[DialogueLine] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        speaker = str(item.get("speaker", "Speaker A"))
        body = str(item.get("text", "")).strip()
        if body:
            lines.append(DialogueLine(
                speaker=speaker,
                text=body,
                pause_after=float(item.get("pause_after", 0.0) or 0.0),
                speed=_opt_float(item, "speed"),
                pitch=_opt_float(item, "pitch"),
            ))
    return lines


_SRT_CUE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})")
_SRT_TIME = r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"


def parse_srt(text: str) -> list[DialogueLine]:
    """Parse SRT subtitles into lines. A speaker may be prefixed: ``Alex: ``."""
    blocks = re.split(r"\n\s*\n", text)
    lines: list[DialogueLine] = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        parts = block.splitlines()
        cue = None
        for part in parts:
            if "-->" in part and _SRT_CUE.search(part):
                cue = part
                break
        if cue is None:
            continue
        # Everything after the timing line is cue text.
        cue_i = next(i for i, p in enumerate(parts) if "-->" in p and _SRT_CUE.search(p))
        body = "\n".join(parts[cue_i + 1:]).strip()
        if not body:
            continue
        m = _SPEAKER_RE.match(body)
        if m:
            speaker = (m.group(1) or m.group(2)).strip().title()
            text_body = m.group(3).strip()
        else:
            speaker, text_body = "Speaker A", body
        if text_body:
            lines.append(DialogueLine(speaker=speaker, text=text_body))
    return lines


def import_file(path: str | Path) -> list[DialogueLine]:
    p = Path(path)
    suffix = p.suffix.lower().lstrip(".")
    text = p.read_text(encoding="utf-8-sig")
    if suffix == "json":
        return parse_json(text)
    if suffix == "csv":
        return parse_csv(text)
    if suffix == "srt":
        return parse_srt(text)
    return parse_txt(text)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_txt(lines: list[DialogueLine]) -> str:
    return "\n".join(f"{line.speaker}: {line.text}" for line in lines if line.text.strip())


def export_csv(lines: list[DialogueLine]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["speaker", "text", "pause_after"])
    for line in lines:
        if line.text.strip():
            writer.writerow([line.speaker, line.text, line.pause_after])
    return buf.getvalue()


def export_json(lines: list[DialogueLine]) -> str:
    payload = [
        {
            "speaker": l.speaker,
            "text": l.text,
            "pause_after": l.pause_after,
            "speed": l.speed,
            "pitch": l.pitch,
        }
        for l in lines
        if l.text.strip()
    ]
    return json.dumps(payload, indent=2)


def export_srt(timed_lines: list[tuple[float, float, str, str]]) -> str:
    """timed_lines: (start_seconds, end_seconds, speaker, text) per cue."""
    cues = []
    for i, (start, end, speaker, text) in enumerate(timed_lines, start=1):
        cues.append(f"{i}\n{_srt_time(start)} --> {_srt_time(end)}\n{speaker}: {text.strip()}\n")
    return "\n".join(cues)


def _srt_time(seconds: float) -> str:
    ms = max(0, int(round(seconds * 1000)))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _opt_float(item: dict, key: str) -> float | None:
    v = item.get(key)
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
