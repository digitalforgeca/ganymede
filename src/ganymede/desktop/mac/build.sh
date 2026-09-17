#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
OUTPUT_DIR="${REPO_DIR}/dist"
APP_NAME="Ganymede.app"
APP_BUNDLE="${OUTPUT_DIR}/${APP_NAME}"
CONTENTS_DIR="${APP_BUNDLE}/Contents"
MACOS_DIR="${CONTENTS_DIR}/MacOS"
RESOURCES_DIR="${CONTENTS_DIR}/Resources"

echo "=== Building Ganymede Desktop App (macOS) ==="
mkdir -p "${MACOS_DIR}" "${RESOURCES_DIR}"

export DEVELOPER_DIR="/Library/Developer/CommandLineTools"

echo "-> Compiling Swift sources with swiftc -O..."
swiftc -O \
    "${SCRIPT_DIR}/DaemonSupervisor.swift" \
    "${SCRIPT_DIR}/WebViewController.swift" \
    "${SCRIPT_DIR}/AppDelegate.swift" \
    "${SCRIPT_DIR}/main.swift" \
    -o "${MACOS_DIR}/Ganymede"

echo "-> Installing Info.plist..."
cp "${SCRIPT_DIR}/Info.plist" "${CONTENTS_DIR}/Info.plist"

# Copy logo as icon if available
if [[ -f "${REPO_DIR}/src/ganymede/web/themes/default/ganymede-logo-dark.png" ]]; then
    cp "${REPO_DIR}/src/ganymede/web/themes/default/ganymede-logo-dark.png" "${RESOURCES_DIR}/AppLogo.png"
fi

echo "-> Setting executable permissions..."
chmod +x "${MACOS_DIR}/Ganymede"

BINARY_SIZE=$(du -h "${MACOS_DIR}/Ganymede" | cut -f1)
BUNDLE_SIZE=$(du -sh "${APP_BUNDLE}" | cut -f1)

echo "=== Build Complete! ==="
echo "  Executable Size : ${BINARY_SIZE}"
echo "  App Bundle Size : ${BUNDLE_SIZE}"
echo "  Bundle Location : ${APP_BUNDLE}"
