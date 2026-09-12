# 🎙️ Kokoro Studio

A local, offline desktop app for generating **podcast-style two-person English
conversations** with the [Kokoro-82M](https://github.com/hexgrad/kokoro) TTS
engine. Built with Python + PySide6 (Qt6).

Designed for YouTube English-learning creators: write a dialogue, assign a
voice + speed + pitch to each speaker, tune the pauses, then render the whole
conversation to a single audio file (with an SRT subtitle file written
alongside). Batch mode renders many episodes at once.

- **100% offline after first run** — model + voices download once from Hugging
  Face and are cached locally.
- **Apple Silicon (MPS) accelerated**, with CPU fallback for Intel Macs,
  Windows and Linux.
- **28 English voices** — American (11F / 9M) and British (4F / 4M).

---

## Requirements

- macOS (Apple Silicon recommended), Windows or Linux
- Python **3.11+** (3.12 recommended)
- [uv](https://docs.astral.sh/uv/) (optional but recommended) or `pip`
- ffmpeg — used for MP3 export and pitch shifting
  - macOS: `brew install ffmpeg`
- espeak-ng — optional OOD fallback for the G2P engine (usually provided
  automatically by the `espeakng-loader` pip package)

## Install & run

```bash
cd kokoro-studio
uv venv .venv --python 3.12
uv pip install -r requirements.txt
uv run python main.py        # or: .venv/bin/python main.py
```

On the very first launch the Kokoro model (~330 MB) and any voices you preview
are downloaded from Hugging Face, then reused forever.

> The app sets `PYTORCH_ENABLE_MPS_FALLBACK=1` automatically so MPS
> acceleration works out of the box on Apple Silicon.

## Quick start

1. **Dialogue Editor** — add lines (`Ctrl+Enter`), choose Speaker A/B voices
   and speeds/pitches in the right-hand panel, tune global pauses, then press
   **▶ Generate Audio**.
2. **Voice Library** — browse the 28 voices, preview any of them, star
   favourites and save presets.
3. **Batch Generator** — drop in `.kstudio` projects (or `.txt` scripts) and
   render them all in serial. Pause / resume / cancel any run, export a CSV
   report.
4. **Settings** — output directory, format (WAV/MP3/FLAC/OGG), sample rate,
   normalization (Peak or LUFS), device, theme.

Each generated file has a matching `.srt` subtitle file written next to it for
use in your video editor.

## Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl+N` / `Ctrl+O` | New / Open project |
| `Ctrl+S` / `Ctrl+Shift+S` | Save / Save As |
| `Ctrl+G` | Generate (Batch: Generate All) |
| `Ctrl+B` | Batch mode |
| `Ctrl+L` | Voice Library |
| `Ctrl+Enter` | Add line |
| `Space` | Preview selected line |
| `Ctrl+Z` / `Ctrl+Shift+Z` | Undo / Redo |
| `Ctrl+Q` | Quit |

## Project files

Projects are saved as `.kstudio` (JSON). Import/export dialogue as
`.txt`, `.json`, `.csv` or `.srt`.

## Tests

```bash
uv run pytest            # core logic + offscreen GUI smoke tests
```

## Packaging an app

```bash
./scripts/build_app.sh    # produces dist/Kokoro Studio.app (large, slow)
```

Then `open "dist/Kokoro Studio.app"`. See `kokoro-studio.spec` for the
PyInstaller configuration. Code-signing / notarization are out of scope.

## License

Apache-2.0. Kokoro-82M weights are Apache-2.0.
