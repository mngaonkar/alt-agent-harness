#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_NAME="Alt Agent Harness"
BUNDLE_NAME="${APP_NAME}.app"
BUILD_DIR="${REPO_ROOT}/dist"
APP_DIR="${BUILD_DIR}/${BUNDLE_NAME}"
CONTENTS_DIR="${APP_DIR}/Contents"
MACOS_DIR="${CONTENTS_DIR}/MacOS"
RESOURCES_DIR="${CONTENTS_DIR}/Resources"
TARGET_INSTALL_DIR="/Applications"

echo "=========================================="
echo " Building macOS App: ${APP_NAME}"
echo "=========================================="
echo "Repository: ${REPO_ROOT}"

# 1. Generate icon if missing
if [[ ! -f "${REPO_ROOT}/assets/AppIcon.icns" ]]; then
  echo "Generating AppIcon.icns..."
  python3 "${REPO_ROOT}/scripts/generate_icon.py" "${REPO_ROOT}/assets/AppIcon.icns"
fi

# 2. Prepare bundle directories
rm -rf "${APP_DIR}"
mkdir -p "${MACOS_DIR}" "${RESOURCES_DIR}"

# 3. Copy Icon
cp "${REPO_ROOT}/assets/AppIcon.icns" "${RESOURCES_DIR}/AppIcon.icns"

# 4. Create PkgInfo
printf "APPL????" > "${CONTENTS_DIR}/PkgInfo"

# 5. Create Info.plist
cat << 'EOF' > "${CONTENTS_DIR}/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>en</string>
    <key>CFBundleDisplayName</key>
    <string>Alt Agent Harness</string>
    <key>CFBundleExecutable</key>
    <string>AltAgentHarness</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleIdentifier</key>
    <string>com.mahadev.alt-agent-harness</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>Alt Agent Harness</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>0.1.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

# 6. Create launch.command inside Resources
cat << EOF > "${RESOURCES_DIR}/launch.command"
#!/usr/bin/env bash
set -eo pipefail

# Window title
printf '\e]0;Alt Agent Harness\a'

# Inherit / set typical macOS PATHs
for p in "\$HOME/.local/bin" "/opt/homebrew/bin" "/opt/homebrew/sbin" "/opt/miniconda3/bin" "/usr/local/bin"; do
  if [ -d "\$p" ] && [[ ":\$PATH:" != *":\$p:"* ]]; then
    export PATH="\$p:\$PATH"
  fi
done

# Source user environment if present
if [ -f "\$HOME/.profile" ]; then
  source "\$HOME/.profile" 2>/dev/null || true
fi

# Locate workspace: env var or this checkout
DEFAULT_WORKSPACE="${REPO_ROOT}"
WORKSPACE="\${ALT_AGENT_WORKSPACE:-\$DEFAULT_WORKSPACE}"

if [ ! -d "\$WORKSPACE" ]; then
  echo "Error: Workspace not found at \$WORKSPACE"
  echo "Set ALT_AGENT_WORKSPACE to your checkout path."
  read -n 1 -s -r -p "Press any key to exit..."
  exit 1
fi

cd "\$WORKSPACE"

echo -e "\033[1;36mStarting Alt Agent Harness...\033[0m"
echo -e "\033[2mWorkspace: \$WORKSPACE\033[0m"
echo ""

if [ -x "./run.sh" ]; then
  exec ./run.sh "\$@"
elif command -v uv >/dev/null 2>&1; then
  if [ -f ".env" ]; then
    exec uv run --env-file .env alt-agent-harness "\$@"
  else
    exec uv run alt-agent-harness "\$@"
  fi
else
  echo "Error: uv is not installed or not in PATH."
  echo "Install it via: curl -LsSf https://astral.sh/uv/install.sh | sh"
  read -n 1 -s -r -p "Press any key to exit..."
  exit 1
fi
EOF

chmod +x "${RESOURCES_DIR}/launch.command"

# 7. Create main executable inside MacOS/
cat << 'EOF' > "${MACOS_DIR}/AltAgentHarness"
#!/usr/bin/env bash
set -eo pipefail

APP_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LAUNCHER="${APP_ROOT}/Contents/Resources/launch.command"

# If already in an interactive terminal or passed arguments in terminal, run directly
if [ -t 0 ] || [ $# -gt 0 ]; then
  exec "${LAUNCHER}" "$@"
fi

# Otherwise (Finder, Spotlight, Launchpad, Dock), launch in Terminal.app
open -a Terminal "${LAUNCHER}"
EOF

chmod +x "${MACOS_DIR}/AltAgentHarness"

# 8. Sign bundle with ad-hoc signature
echo "Signing bundle..."
codesign --force --deep --sign - "${APP_DIR}"

echo "[OK] Built bundle at: ${APP_DIR}"

# 9. Installation to /Applications
if [[ "${1:-}" == "--install" || "${INSTALL:-}" == "1" || -z "${1:-}" ]]; then
  echo "Installing to ${TARGET_INSTALL_DIR}/${BUNDLE_NAME}..."
  rm -rf "${TARGET_INSTALL_DIR}/${BUNDLE_NAME}"
  cp -R "${APP_DIR}" "${TARGET_INSTALL_DIR}/${BUNDLE_NAME}"
  
  # Register with LaunchServices
  LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
  if [[ -x "${LSREGISTER}" ]]; then
    "${LSREGISTER}" -f "${TARGET_INSTALL_DIR}/${BUNDLE_NAME}" || true
  fi
  touch "${TARGET_INSTALL_DIR}/${BUNDLE_NAME}"
  echo "[OK] Installed successfully to ${TARGET_INSTALL_DIR}/${BUNDLE_NAME}"
fi

echo ""
echo "Done! You can now launch '${APP_NAME}' from:"
echo "  • Applications folder in Finder"
echo "  • Spotlight (Cmd + Space, type 'Alt Agent Harness')"
echo "  • Launchpad or Dock"
echo "  • Terminal: open -a '${APP_NAME}'"
