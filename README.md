# Epson LabelWorks LW-600P — open driver and label editor for macOS

Prints to the LW-600P over USB on modern macOS (including Apple Silicon), with
no Epson kext or Intel binaries. The wire protocol was recovered from Epson's
last driver (1.37); see [PROTOCOL.md](PROTOCOL.md).

## Setup

```bash
brew install libusb python-tk@3.14
"$(brew --prefix)/bin/python3.14" -m venv .venv && .venv/bin/pip install -e '.[test]'
```

Run these from the cloned folder.

## Label Editor

Double-click **LW-600P Label Editor.app** in the cloned folder (or run
`.venv/bin/lw600p-editor`). The app runs the editor from the folder it sits
in, so keep it next to `.venv`. To put it in the Dock, drag it there; don't
move it to Applications. If you downloaded a ZIP instead of cloning, macOS may
block the first launch: Control-click the app and choose **Open**.

Type the label text, pick a font, size and alignment, and use the live
preview to check it. The dashed lines mark the printable band and the red
lines mark the cuts. **Detect** reads the loaded tape width from the printer.
**Print** (⌘P) warns you if the loaded tape doesn't match the label. **Use
Image…** prints a picture instead of text. Settings are remembered between
sessions.

## Command line

```bash
.venv/bin/lw600p status
.venv/bin/lw600p print "Hello"                       # tape width auto-detected
.venv/bin/lw600p print "Line one\nLine two" --tape 24 --copies 3
.venv/bin/lw600p print --image logo.png --tape 12
.venv/bin/lw600p feed --cut
```

Useful options: `--margin MM`, `--density -3..3`, `--cut each|end|none`,
`--bold`, `--font PATH`, `--mirror`, `--flip` (if labels print upside down),
`--preview out.png`, `--output job.bin` (dry run, no printer needed).

Inspect a dry-run job: `.venv/bin/python -m lw600p.decode job.bin out.png`.

Tests: `.venv/bin/python -m pytest -q`.
