#!/bin/sh
# Build a double-clickable "LW-600P Label Editor.app" that runs the editor
# from this checkout's virtualenv. Re-run after moving the project folder.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="${1:-$ROOT/LW-600P Label Editor.app}"
PY="$ROOT/.venv/bin/python"

[ -x "$PY" ] || { echo "missing $PY — create the venv first (see README)"; exit 1; }

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cat > "$APP/Contents/MacOS/LabelEditor" <<EOF
#!/bin/sh
exec "$PY" -m lw600p.editor
EOF
chmod +x "$APP/Contents/MacOS/LabelEditor"
cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>LW-600P Label Editor</string>
  <key>CFBundleDisplayName</key><string>LW-600P Label Editor</string>
  <key>CFBundleIdentifier</key><string>local.lw600p.editor</string>
  <key>CFBundleExecutable</key><string>LabelEditor</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
EOF
echo "Built $APP"
