# TASK: Build a Kokoro TTS Desktop Application

## PROJECT OVERVIEW
Build a fully-featured, cross-platform desktop application called **"Kokoro Studio"** 
using Python that wraps the Kokoro TTS engine. The app must run natively on 
macOS (Apple Silicon M-series optimized), with support for Windows and Linux.

The app is designed for a YouTube English-learning channel creator who needs 
to generate podcast-style two-person English conversations locally, with 
fine-grained control over voices, speed, pauses, and batch generation.

---

## 🎯 CORE REQUIREMENTS

### Tech Stack (MANDATORY)
- **Language:** Python 3.11+
- **GUI Framework:** PySide6 (Qt6) — preferred for native look, but PyQt6 acceptable
- **TTS Engine:** Kokoro (`pip install kokoro soundfile misaki[en]`)
- **Audio:** soundfile, numpy, pydub (for silence/pause insertion)
- **Packaging:** PyInstaller or Briefcase (must produce .app for macOS)
- **Config:** JSON or TOML files stored in user's home directory
- **Platform:** Cross-platform (macOS primary, Windows/Linux secondary)

### Hardware Target
- Optimized for Apple Silicon (M1/M2/M3/M4/M5) using MPS backend
- Must work on Intel Macs and Windows/Linux as fallback
- No cloud dependencies — 100% offline

---

## 🏗️ APPLICATION ARCHITECTURE

kokoro-studio/
├── main.py                    # Entry point
├── app/
│   ├── __init__.py
│   ├── ui/
│   │   ├── main_window.py     # Main window
│   │   ├── dialogue_editor.py # Conversation editor
│   │   ├── voice_panel.py     # Voice selection
│   │   ├── settings_dialog.py # Settings
│   │   └── widgets/           # Reusable widgets
│   ├── core/
│   │   ├── tts_engine.py      # Kokoro wrapper
│   │   ├── audio_processor.py # Silence, normalization, mixing
│   │   ├── batch_runner.py    # Batch generation (threaded)
│   │   └── project.py         # Project data model
│   ├── models/
│   │   ├── dialogue.py        # DialogueLine dataclass
│   │   └── voice.py           # Voice metadata
│   ├── utils/
│   │   ├── config.py          # App config
│   │   ├── paths.py           # File paths
│   │   └── logger.py          # Logging
│   └── assets/
│       ├── icons/
│       └── styles/
├── tests/
├── requirements.txt
├── pyproject.toml
└── README.md

---

## 🎨 USER INTERFACE — DETAILED SPEC

### Main Window Layout

┌──────────────────────────────────────────────────────────────┐
│  Kokoro Studio                          [─][□][✕]            │
├──────────────────────────────────────────────────────────────┤
│  File   Edit   Voices   Batch   Help                         │
├──────────────────────────────────────────────────────────────┤
│ ┌──────────────────────┐  ┌────────────────────────────────┐ │
│ │  📝 DIALOGUE EDITOR  │  │  🎙️ VOICE PANEL                │ │
│ │                      │  │                                │ │
│ │  [Speaker] [Text]    │  │  Speaker A (Alex):             │ │
│ │  ┌─────┬───────────┐ │  │  [am_michael ▼]                │ │
│ │  │Alex │ Hello...  │ │  │  Speed: [0.85] ────●───        │ │
│ │  ├─────┼───────────┤ │  │  Pitch: [1.0]  ────●───        │ │
│ │  │Mia  │ Hi...     │ │  │  [🔊 Preview]                  │ │
│ │  ├─────┼───────────┤ │  │                                │ │
│ │  │Alex │ Can I...  │ │  │  Speaker B (Mia):              │ │
│ │  └─────┴───────────┘ │  │  [af_heart ▼]                  │ │
│ │                      │  │  Speed: [0.85] ────●───        │ │
│ │  [+ Add Line]        │  │  Pitch: [1.0]  ────●───        │ │
│ │  [🗑 Delete] [↑↓]    │  │  [🔊 Preview]                  │ │
│ │                      │  │                                │ │
│ │                      │  │  ─── Global Settings ───       │ │
│ │                      │  │  Pause between lines: [0.5s]   │ │
│ │                      │  │  Pause between speakers: [0.8s]│ │
│ │                      │  │  Output format: [WAV ▼]        │ │
│ │                      │  │  Sample rate: [24000 ▼]        │ │
│ └──────────────────────┘  └────────────────────────────────┘ │
├──────────────────────────────────────────────────────────────┤
│  [▶ Generate Audio]  [📦 Batch Mode]  [💾 Save Project]      │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  [Progress]    │
├──────────────────────────────────────────────────────────────┤
│  Status: Ready  |  Audio length: 00:00  |  GPU: MPS          │
└──────────────────────────────────────────────────────────────┘

### Tabs / Sections

**Tab 1: Dialogue Editor**
- Table with columns: Speaker (dropdown), Text (editable), Pause After (seconds)
- Buttons: Add Line, Delete Line, Move Up, Move Down, Duplicate
- Import from: .txt, .json, .csv, .srt
- Export to: .json, .csv, .txt
- Right-click context menu with copy/paste/insert

**Tab 2: Voice Library**
- Grid of all Kokoro voices with preview buttons
- Filter by: gender, accent, quality
- Shows: voice ID, gender, accent, description
- Favorite voices (star system)
- Custom voice presets (save/load)

**Tab 3: Batch Generator**
- Table of projects (each row = one video)
- Columns: Name, Status, Duration, Output Path
- Buttons: Add Project, Remove, Generate All, Generate Selected
- Progress bar per project
- Queue management (pause, resume, cancel)
- Load from folder of scripts

**Tab 4: Settings**
- Model path (default: auto-download)
- Default voices
- Output directory
- Audio normalization (on/off + LUFS target)
- Theme (light/dark/system)
- GPU/CPU selection
- Log level

**Tab 5: About**
- Version, credits, license info

---

## 🔧 FUNCTIONAL REQUIREMENTS

### F1: Dialogue Editor
- Add/edit/delete/reorder dialogue lines
- Each line has: speaker, text, optional pause override
- Real-time word count and estimated duration
- Undo/redo (Ctrl+Z / Ctrl+Shift+Z)
- Auto-save every 60 seconds

### F2: Voice Management
- Load all Kokoro voices dynamically
- Preview button (generates 3-sec sample)
- Speed control: 0.5x – 1.5x (slider + spinbox)
- Pitch control: -2 to +2 semitones
- Voice presets saved to JSON

### F3: Audio Generation
- Generate full dialogue as single file
- Insert silence between lines based on config
- Support: WAV, MP3, FLAC, OGG output
- Normalization option (peak / LUFS)
- Multi-threaded generation (UI stays responsive)
- Cancel mid-generation
- Show progress bar + estimated time

### F4: Batch Generation
- Load multiple projects (JSON format)
- Queue system with threading
- Generate all with one click
- Per-file progress and status
- Error handling: continue on failure, log errors
- Export batch report (CSV)

### F5: Project Management
- Save/load projects as .kstudio files (JSON)
- Recent files list
- Auto-recovery on crash
- Export dialogue as subtitle (.srt) with timing

### F6: Keyboard Shortcuts
- Ctrl+N: New project
- Ctrl+O: Open project
- Ctrl+S: Save
- Ctrl+Shift+S: Save As
- Ctrl+G: Generate
- Ctrl+B: Batch mode
- Ctrl+Enter: Add new line
- Space: Preview selected line
- Ctrl+Q: Quit

---

## 🎵 AUDIO PROCESSING SPEC

### Silence Insertion
- Between lines (same speaker): `pause_between_lines` (default 0.5s)
- Between speakers (A→B or B→A): `pause_between_speakers` (default 0.8s)
- Configurable per-line override

### Normalization
- Peak normalization: -1 dBFS target
- LUFS normalization: -16 LUFS (podcast standard)
- Optional: use pyloudnorm for LUFS

### Post-processing Chain
1. Generate per-line audio via Kokoro
2. Apply speed/pitch (if not handled by Kokoro)
3. Insert silence
4. Concatenate
5. Normalize
6. Export

### Audio Format
- Default: WAV, 24000 Hz, 16-bit PCM
- Optional: MP3 (via pydub/ffmpeg), FLAC, OGG

---

## 🧵 THREADING MODEL

- **Main thread:** GUI only
- **Worker thread:** TTS generation (QThread or concurrent.futures)
- **Signals:** progress_update(int), line_generated(str), error(str), finished(str)
- **Cancellation:** threading.Event checked between lines
- **Queue:** QThreadPool for batch jobs

```python
# Example signal pattern
class TTSWorker(QObject):
    progress = Signal(int)
    line_done = Signal(int, str)  # index, path
    error = Signal(str)
    finished = Signal(str)  # output path
    
    @Slot()
    def run(self):
        # generation logic
        pass