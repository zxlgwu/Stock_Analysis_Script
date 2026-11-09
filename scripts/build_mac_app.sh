#!/bin/bash
# Build a double-clickable Stock Agent.app that uses the stock_agent conda env.
# Quitting the window stops the app server. It does not stop Ollama.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/Stock Agent.app"
MACOS="$APP/Contents/MacOS"
PYTHON="/opt/homebrew/Caskroom/miniforge/base/envs/stock_agent/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "The stock_agent conda environment was not found at $PYTHON" >&2
  exit 1
fi

rm -rf "$APP"
mkdir -p "$MACOS"

cat > "$MACOS/stock-agent" << EOF
#!/bin/bash
set -euo pipefail
ROOT="\$(cd "\$(dirname "\$0")/../../.." && pwd)"
PY="$PYTHON"
cd "\$ROOT"
export PYTHONPATH="\$ROOT\${PYTHONPATH:+:\$PYTHONPATH}"
exec "\$PY" -m stock_agent.ui "\$@"
EOF
chmod +x "$MACOS/stock-agent"

cat > "$APP/Contents/Info.plist" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>Stock Agent</string>
  <key>CFBundleDisplayName</key>
  <string>Stock Agent</string>
  <key>CFBundleIdentifier</key>
  <string>local.stockagent.app</string>
  <key>CFBundleVersion</key>
  <string>1.0.0</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0.0</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleExecutable</key>
  <string>stock-agent</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
EOF

echo "Built $APP"
