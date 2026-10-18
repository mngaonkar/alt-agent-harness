#!/usr/bin/env bash
# Build a standalone "Alt Agent Harness.app": it bundles its own Python, the
# harness and its dependencies, so the target Mac needs nothing installed.
# The app is built for this machine's CPU architecture.
#
#   ./scripts/build_macos_app.sh               build and install to /Applications
#   ./scripts/build_macos_app.sh --no-install  build into dist/ only
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
PYTHON_DIR="${RESOURCES_DIR}/python"
TARGET_INSTALL_DIR="/Applications"
APP_VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "${REPO_ROOT}/pyproject.toml" | head -1)"
BUILD_NUMBER="${BUILD_NUMBER:-1}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"

echo "=========================================="
echo " Building macOS App: ${APP_NAME} ${APP_VERSION}"
echo "=========================================="
echo "Repository: ${REPO_ROOT}"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to build the app: https://docs.astral.sh/uv/" >&2
  exit 1
fi

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
cat << EOF > "${CONTENTS_DIR}/Info.plist"
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
    <string>${APP_VERSION}</string>
    <key>CFBundleVersion</key>
    <string>${BUILD_NUMBER}</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

# 6. Bundle a relocatable Python (uv-managed python-build-standalone)
echo "Bundling Python ${PYTHON_VERSION}..."
uv python install "${PYTHON_VERSION}"
# Pick the install from uv's own directory: `uv python find` would prefer an
# active conda env or virtualenv over a managed Python.
ARCH="$(uname -m | sed 's/arm64/aarch64/')"
PYTHON_HOME="$(ls -d "$(uv python dir)"/cpython-"${PYTHON_VERSION}".*-macos-"${ARCH}"-none 2>/dev/null | sort -V | tail -1)"
if [[ -z "${PYTHON_HOME}" || ! -x "${PYTHON_HOME}/bin/python3" ]]; then
  echo "No uv-managed Python ${PYTHON_VERSION} found for ${ARCH}" >&2
  exit 1
fi
echo "Using ${PYTHON_HOME}"
cp -R "${PYTHON_HOME}" "${PYTHON_DIR}"
rm -f "${PYTHON_DIR}"/lib/python3*/EXTERNALLY-MANAGED
rm -rf "${PYTHON_DIR}"/lib/python3*/test "${PYTHON_DIR}"/lib/python3*/idlelib

# 7. Install the harness and its locked dependencies into the bundled Python
echo "Installing alt-agent-harness and dependencies..."
REQUIREMENTS="$(mktemp)"
trap 'rm -f "${REQUIREMENTS}"' EXIT
(cd "${REPO_ROOT}" && uv export --frozen --no-dev --no-emit-project --no-hashes -q > "${REQUIREMENTS}")
uv pip install --python "${PYTHON_DIR}/bin/python3" --no-cache -q -r "${REQUIREMENTS}"
uv pip install --python "${PYTHON_DIR}/bin/python3" --no-cache -q --no-deps "${REPO_ROOT}"
# Precompile so Python never writes __pycache__ into the signed bundle
"${PYTHON_DIR}/bin/python3" -m compileall -q "${PYTHON_DIR}/lib" >/dev/null || true

# 8. Bundle the starter workspace (skills + example config)
mkdir -p "${RESOURCES_DIR}/workspace"
(cd "${REPO_ROOT}" && git ls-files -z skills config.example.json README.md \
  | rsync -a --from0 --files-from=- . "${RESOURCES_DIR}/workspace/")

# 9. Create launch.command inside Resources
cat << 'EOF' > "${RESOURCES_DIR}/launch.command"
#!/usr/bin/env bash
set -eo pipefail

# Window title
printf '\e]0;Alt Agent Harness\a'

RESOURCES="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${RESOURCES}/python/bin/python3"

# Make user tools (brew, ~/.local/bin) visible to run_bash
for p in "$HOME/.local/bin" "/opt/homebrew/bin" "/opt/homebrew/sbin" "/usr/local/bin"; do
  if [ -d "$p" ] && [[ ":$PATH:" != *":$p:"* ]]; then
    export PATH="$p:$PATH"
  fi
done

# Workspace holds config.json, .env, skills and /tmp. ALT_AGENT_WORKSPACE
# points the app at another one, e.g. a git checkout.
if [ -n "${ALT_AGENT_WORKSPACE:-}" ]; then
  WORKSPACE="${ALT_AGENT_WORKSPACE}"
else
  WORKSPACE="$HOME/Library/Application Support/Alt Agent Harness"
  # Sync bundled skills in. Nothing is deleted, so config.json, .env and
  # skills the agent wrote survive upgrades.
  mkdir -p "$WORKSPACE"
  rsync -a "${RESOURCES}/workspace/" "$WORKSPACE/"
fi

if [ ! -d "$WORKSPACE" ]; then
  echo "Error: Workspace not found at $WORKSPACE"
  read -n 1 -s -r -p "Press any key to exit..."
  exit 1
fi

cd "$WORKSPACE"

echo -e "\033[1;36mStarting Alt Agent Harness...\033[0m"
echo -e "\033[2mWorkspace: $WORKSPACE\033[0m"
echo ""

export PYTHONDONTWRITEBYTECODE=1
exec "$PYTHON" -I -c 'import sys; from agent.cli import main; sys.exit(main())' \
  --workspace "$WORKSPACE" "$@"
EOF

chmod +x "${RESOURCES_DIR}/launch.command"

# 10. Create main executable inside MacOS/
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

# 11. Sign with ad-hoc signatures: nested Mach-O files first, then the bundle
echo "Signing bundle..."
find "${PYTHON_DIR}" -type f \( -perm -u+x -o -name '*.so' -o -name '*.dylib' \) -print0 \
  | while IFS= read -r -d '' f; do
      if file -b "$f" | grep -q 'Mach-O'; then
        codesign --force --sign - "$f"
      fi
    done
codesign --force --sign - "${APP_DIR}"

echo "[OK] Built bundle at: ${APP_DIR} ($(du -sh "${APP_DIR}" | cut -f1))"

# 12. Installation to /Applications (skip with --no-install)
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
