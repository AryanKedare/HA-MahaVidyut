#!/usr/bin/env bash
# Install MahaVidyut into a Home Assistant configuration directory.
# Usage: bash install.sh [/path/to/homeassistant/config]
# Uses bundled files when available; otherwise downloads the main branch.

set -euo pipefail

REPO_URL="https://github.com/AryanKedare/HA-MahaVidyut"
BRANCH="main"
INTEGRATION_NAME="aesl_smart_meter"
TMP_DIR=""
STAGE_DIR=""
BACKUP_DIR=""
DEST_DIR=""

info() { printf '[INFO] %s\n' "$*"; }
ok() { printf '[ OK ] %s\n' "$*"; }
fail() {
  printf '[ERROR] %s\n' "$*" >&2
  exit 1
}

cleanup() {
  local status=$?
  trap - EXIT
  if [[ "$status" -ne 0 && -n "$BACKUP_DIR" && -d "${BACKUP_DIR}/${INTEGRATION_NAME}" && ! -e "$DEST_DIR" && ! -L "$DEST_DIR" ]]; then
    if mv -- "${BACKUP_DIR}/${INTEGRATION_NAME}" "$DEST_DIR"; then
      info "Restored the previous installation after the failed upgrade."
    else
      printf '[ERROR] Restore the previous installation from %s\n' "${BACKUP_DIR}/${INTEGRATION_NAME}" >&2
    fi
  fi
  if [[ -n "$STAGE_DIR" && -d "$STAGE_DIR" ]]; then
    rm -rf -- "$STAGE_DIR"
  fi
  if [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then
    rm -rf -- "$TMP_DIR"
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  printf 'Usage: bash install.sh [/path/to/homeassistant/config]\nDefault config directory: /config\n'
  exit 0
fi
[[ "$#" -le 1 ]] || fail "Usage: bash install.sh [/path/to/homeassistant/config]"

CONFIG_DIR="${1:-/config}"
[[ -d "$CONFIG_DIR" ]] || fail "Config directory '$CONFIG_DIR' does not exist."
CONFIG_DIR="$(cd -- "$CONFIG_DIR" && pwd -P)"
CUSTOM_COMPONENTS_DIR="${CONFIG_DIR}/custom_components"
DEST_DIR="${CUSTOM_COMPONENTS_DIR}/${INTEGRATION_NAME}"
[[ ! -L "$DEST_DIR" ]] || fail "Destination '$DEST_DIR' is a symbolic link; install manually."
[[ ! -e "$DEST_DIR" || -d "$DEST_DIR" ]] || fail "Destination '$DEST_DIR' is not a directory."

SCRIPT_DIR=""
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
  SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
fi

if [[ -n "$SCRIPT_DIR" && -d "${SCRIPT_DIR}/custom_components/${INTEGRATION_NAME}" ]]; then
  SRC_DIR="${SCRIPT_DIR}/custom_components/${INTEGRATION_NAME}"
  info "Using bundled integration files from ${SRC_DIR}..."
else
  for cmd in curl unzip; do
    command -v "$cmd" >/dev/null 2>&1 || fail "'$cmd' is required but not installed."
  done
  TMP_DIR="$(mktemp -d)"
  ZIP_FILE="${TMP_DIR}/HA-MahaVidyut.zip"
  ZIP_URL="${REPO_URL}/archive/refs/heads/${BRANCH}.zip"
  info "Downloading MahaVidyut from ${REPO_URL} (${BRANCH})..."
  curl -fsSL --retry 2 --connect-timeout 15 --max-time 120 "$ZIP_URL" -o "$ZIP_FILE" || fail "Download failed."
  unzip -q "$ZIP_FILE" -d "$TMP_DIR" || fail "Could not extract the downloaded archive."
  SRC_DIR="${TMP_DIR}/HA-MahaVidyut-${BRANCH}/custom_components/${INTEGRATION_NAME}"
  [[ -d "$SRC_DIR" ]] || fail "Could not locate the MahaVidyut integration files."
fi

RUNTIME_FILES=(
  "__init__.py"
  "api.py"
  "config_flow.py"
  "const.py"
  "coordinator.py"
  "manifest.json"
  "sensor.py"
  "strings.json"
  "translations/en.json"
)

for file in "${RUNTIME_FILES[@]}"; do
  [[ -f "${SRC_DIR}/${file}" && ! -L "${SRC_DIR}/${file}" ]] || fail "Required integration file is missing or is a symbolic link: ${file}"
done

# Stage all runtime files before moving an existing installation out of the way.
mkdir -p "$CUSTOM_COMPONENTS_DIR"
STAGE_DIR="$(mktemp -d "${CUSTOM_COMPONENTS_DIR}/.aesl_smart_meter-install.XXXXXX")"
mkdir -p "${STAGE_DIR}/translations"
for file in "${RUNTIME_FILES[@]}"; do
  cp -- "${SRC_DIR}/${file}" "${STAGE_DIR}/${file}"
  chmod 644 "${STAGE_DIR}/${file}"
done
chmod 755 "$STAGE_DIR" "${STAGE_DIR}/translations"

if [[ -d "$DEST_DIR" ]]; then
  BACKUP_ROOT="${CONFIG_DIR}/.aesl_smart_meter_backups"
  mkdir -p "$BACKUP_ROOT"
  BACKUP_DIR="$(mktemp -d "${BACKUP_ROOT}/backup.XXXXXX")"
  info "Backing up the existing installation to ${BACKUP_DIR}/${INTEGRATION_NAME}..."
  mv -- "$DEST_DIR" "${BACKUP_DIR}/${INTEGRATION_NAME}"
fi

mv -- "$STAGE_DIR" "$DEST_DIR"
STAGE_DIR=""
ok "Installed MahaVidyut to ${DEST_DIR}."
if [[ -n "$BACKUP_DIR" ]]; then
  info "Previous integration files: ${BACKUP_DIR}/${INTEGRATION_NAME}"
fi
printf '\nRestart Home Assistant.\n'
printf 'Existing meter: keep the entry and complete its repair or use Reconfigure.\n'
printf 'New installation: add AESL Smart Meter (Unofficial) from Settings -> Devices & services.\n'
