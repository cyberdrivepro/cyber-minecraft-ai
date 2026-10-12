# ============================================================================
# Cyber Minecraft AI — universal Linux uninstaller
#
#   ./scripts/uninstall.sh [--keep-data] [--purge]
#
# Default: removes the service, venv and caches but KEEPS your data directory
# (worlds, backups, database, mods) and your .env so you can reinstall later.
# --purge: deletes all data and configuration as well. Asks for confirmation.
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="keep"
[[ "${1:-}" == "--purge" ]] && MODE="purge"
[[ "${1:-}" == "--keep-data" ]] && MODE="keep"

SUDO=""
if [[ "$(id -u)" -ne 0 ]] && command -v sudo >/dev/null 2>&1; then SUDO="sudo"; fi

SERVICE_NAME="cyber-minecraft-ai"

echo "Cyber Minecraft AI uninstaller (mode: $MODE)"

# 1. Stop and remove the systemd service if present
if command -v systemctl >/dev/null 2>&1 && [[ -f /etc/systemd/system/${SERVICE_NAME}.service ]]; then
    echo "Stopping and removing systemd service..."
    $SUDO systemctl stop ${SERVICE_NAME} 2>/dev/null || true
    $SUDO systemctl disable ${SERVICE_NAME} 2>/dev/null || true
    $SUDO rm -f /etc/systemd/system/${SERVICE_NAME}.service
    $SUDO systemctl daemon-reload
fi

# 2. Stop a CLI-started instance if the PID file exists
if [[ -f /tmp/cyber-minecraft-ai.pid ]]; then
    PID="$(cat /tmp/cyber-minecraft-ai.pid)"
    echo "Stopping background instance (PID ${PID})..."
    kill "$PID" 2>/dev/null || true
    rm -f /tmp/cyber-minecraft-ai.pid
fi

# 3. Remove virtualenv
if [[ -d "${REPO_ROOT}/.venv" ]]; then
    echo "Removing virtual environment..."
    rm -rf "${REPO_ROOT}/.venv"
fi

# 4. Data handling
if [[ "$MODE" == "purge" ]]; then
    echo ""
    echo "This will PERMANENTLY DELETE all servers, worlds, backups, mod projects"
    echo "and the database under ${REPO_ROOT}/data plus your .env file."
    read -r -p "Type DELETE to confirm: " answer
    if [[ "$answer" == "DELETE" ]]; then
        rm -rf "${REPO_ROOT}/data"
        rm -f "${REPO_ROOT}/.env"
        echo "All data deleted."
    else
        echo "Purge cancelled — data kept."
    fi
else
    echo ""
    echo "Kept: ${REPO_ROOT}/data (worlds, backups, database) and .env"
    echo "Reinstall later with ./scripts/install.sh — your data will be picked up."
fi

echo "Uninstall complete."
