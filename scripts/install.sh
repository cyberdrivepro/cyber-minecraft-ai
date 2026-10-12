#!/usr/bin/env bash
# ============================================================================
# Cyber Minecraft AI — universal Linux installer
#
#   git clone https://github.com/cyberdrivepro/cyber-minecraft-ai.git
#   cd cyber-minecraft-ai
#   chmod +x scripts/install.sh
#   ./scripts/install.sh
#
# Noninteractive mode is the default; every question is answered "yes"
# automatically. Pass --interactive to re-enable prompts.
# Supported: Ubuntu / Debian and compatible distributions; generic Linux with
# python3.9+. Docker Desktop / Hugging Face Spaces use Dockerfile instead.
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="${REPO_ROOT}/install.log"
NONINTERACTIVE=true
[[ "${1:-}" == "--interactive" ]] && NONINTERACTIVE=false

log()  { echo -e "\033[36m[install]\033[0m $*"; }
ok()   { echo -e "\033[32m[ok]\033[0m $*"; }
warn() { echo -e "\033[33m[warn]\033[0m $*"; }
err()  { echo -e "\033[31m[error]\033[0m $*"; }
trap 'err "Installation failed at line $LINENO. See ${LOG_FILE}"' ERR
exec > >(tee -a "$LOG_FILE") 2>&1

SUDO=""
if [[ "$(id -u)" -ne 0 ]] && command -v sudo >/dev/null 2>&1; then SUDO="sudo"; fi

prompt() {
    # prompt "question" -> echoes "y"/"n"; auto-YES in the default fully
    # automatic mode, real question only with --interactive
    if $NONINTERACTIVE; then echo "y"; return; fi
    read -r -p "$1 [Y/n] " answer </dev/tty
    [[ "$answer" == "n" || "$answer" == "N" ]] && echo "n" || echo "y"
}

log "Cyber Minecraft AI installer starting in ${REPO_ROOT}"

# ----------------------------------------------------------- detect platform
OS_ID="unknown"; OS_VERSION="unknown"
if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    OS_ID="${ID:-unknown}"; OS_VERSION="${VERSION_ID:-unknown}"
fi
ARCH="$(uname -m)"
RAM_MB="$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo 2>/dev/null || echo unknown)"
log "Detected: ${OS_ID} ${OS_VERSION} (${ARCH}), RAM ${RAM_MB} MB"

case "$OS_ID" in
    ubuntu|debian|linuxmint|pop|raspbian) PKG="apt" ;;
    *) PKG="none"; warn "Unrecognized distribution '${OS_ID}' — using generic Linux install path (no packages will be installed automatically)" ;;
esac

# --------------------------------------------------------------- system deps
if [[ "$PKG" == "apt" ]]; then
    log "Installing system packages (python3-venv, python3-pip, curl)..."
    $SUDO apt-get update -qq
    $SUDO apt-get install -y -qq python3-venv python3-pip curl unzip >/dev/null
    ok "System packages installed"
fi

# --------------------------------------------------------------- disk space
FREE_MB="$(df -Pm "$REPO_ROOT" | awk 'NR==2 {print $4}')"
if [[ "$FREE_MB" -lt 5120 ]]; then
    warn "Only ${FREE_MB} MB free on this disk. Real Java servers and worlds need space; the AI stack can fail to install below ~5 GB (a CPU-only fallback is attempted automatically)."
fi

# ------------------------------------------------------------------ java 21
java_major() {
    java -version 2>&1 | head -1 | sed -n 's/.*version "\([0-9]*\).*/\1/p'
}

JAVA_VER=""
if command -v java >/dev/null 2>&1; then
    JAVA_VER="$(java_major || true)"
fi
if [[ -n "$JAVA_VER" ]] && [[ "$JAVA_VER" -ge 17 ]]; then
    ok "Java ${JAVA_VER} already present — no installation needed: $(java -version 2>&1 | head -1)"
else
    if [[ -n "$JAVA_VER" ]]; then
        log "Java ${JAVA_VER} detected but Java 17/21 is required for real Minecraft server hosting — installing OpenJDK 21..."
    else
        log "Java 21 is required for real Minecraft server hosting and Fabric mod builds — installing OpenJDK 21..."
    fi
    if [[ "$PKG" == "apt" ]] && [[ "$(uname -m)" != "armv7l" ]]; then
        $SUDO apt-get install -y -qq openjdk-21-jdk-headless >/dev/null && ok "Java 21 installed" \
            || warn "OpenJDK 21 install failed — install Java manually (https://adoptium.net)"
    else
        warn "No automatic Java install for this distribution. Install Java 17/21 from https://adoptium.net"
    fi
fi

# --------------------------------------------------------------- python venv
PY=python3
if ! command -v "$PY" >/dev/null 2>&1; then err "python3 not found"; exit 1; fi
PYVER="$($PY -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
log "Python ${PYVER} detected"
if [[ "$(echo "$PYVER" | cut -d. -f1)" -eq 3 && "$(echo "$PYVER" | cut -d. -f2)" -lt 9 ]]; then
    err "Python 3.9+ required (found ${PYVER})"; exit 1
fi

cd "$REPO_ROOT"
if [[ ! -d .venv ]]; then
    log "Creating virtual environment (.venv)..."
    $PY -m venv .venv || { err "python3-venv is missing"; [[ "$PKG" == "apt" ]] && $SUDO apt-get install -y python3-venv && $PY -m venv .venv; }
fi
# shellcheck disable=SC1091
source .venv/bin/activate
log "Installing Python dependencies (this can take a few minutes)..."
pip install --upgrade pip >/dev/null
# Install the CPU-only torch wheel FIRST so the CUDA variant (~2.5 GB of
# nvidia/cuda wheels) is never downloaded — this is what fills small disks.
# The platform runs its AI features on CPU unless a GPU is actually present.
if ! pip install --only-binary=:all: torch --index-url https://download.pytorch.org/whl/cpu >/dev/null 2>&1; then
    warn "CPU torch wheel unavailable for ${PYVER} — falling back to the default pip index"
fi
if pip install -r requirements.txt; then
    ok "Python dependencies installed"
else
    # Self-healing: small disks / offline AI stacks can retry without the
    # heavy ML extras (torch/transformers). The heuristic planner covers them.
    warn "Full dependency install failed — retrying without the heavy ML extras (torch, transformers, accelerate)..."
    grep -vE '^(torch|transformers|accelerate|safetensors)' requirements.txt > /tmp/cma-requirements-lite.txt
    pip install -r /tmp/cma-requirements-lite.txt
    ok "Python dependencies installed (lite mode — local AI models disabled, heuristic AI planner active)"
fi

# --------------------------------------------------------------- environment
if [[ ! -f .env ]]; then
    log "Creating .env from .env.example ..."
    cp .env.example .env
    GENERATED_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
    if [[ "$OS" != "Windows" ]]; then
        sed -i "s|^ADMIN_TOKEN=.*|ADMIN_TOKEN=${GENERATED_TOKEN}|" .env
    fi
    ok ".env created with a generated ADMIN_TOKEN (check .env for other options)"
    if ! $NONINTERACTIVE; then
        read -r -p "Telegram bot token (leave empty to configure later): " tg_token </dev/tty || tg_token=""
        if [[ -n "$tg_token" ]]; then
            sed -i "s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=${tg_token}|" .env
            ok "Telegram token saved"
        fi
    fi
else
    ok "Existing .env preserved (upgrade-safe)"
fi

# ------------------------------------------------------------------ database
log "Initializing database..."
DATA_DIR="$("$PY" -c "import os; print(os.environ.get('DATA_DIR', './data'))")"
mkdir -p "$DATA_DIR"
"$PY" - <<'EOF'
from storage.database import init_db
init_db()
print("database ready")
EOF
ok "Database initialized"

# -------------------------------------------------------------------- systemd
SERVICE_NAME="cyber-minecraft-ai"
if command -v systemctl >/dev/null 2>&1 && [[ -d /etc/systemd/system ]] \
   && [[ "$(prompt 'Install a systemd service (auto-start on boot)?')" == "y" ]]; then
    log "Installing systemd service '${SERVICE_NAME}'..."
    $SUDO tee /etc/systemd/system/${SERVICE_NAME}.service >/dev/null <<EOF
[Unit]
Description=Cyber Minecraft AI platform
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=${REPO_ROOT}
ExecStart=${REPO_ROOT}/.venv/bin/python ${REPO_ROOT}/main.py
Restart=on-failure
RestartSec=5
MemoryMax=2G
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
    $SUDO systemctl daemon-reload
    $SUDO systemctl enable ${SERVICE_NAME} >/dev/null 2>&1
    $SUDO systemctl start ${SERVICE_NAME}
    sleep 3
    if systemctl is-active --quiet ${SERVICE_NAME}; then
        ok "Service running: systemctl status ${SERVICE_NAME}"
    else
        warn "Service did not report active yet — check: journalctl -u ${SERVICE_NAME} -n 50"
    fi
    echo "Service management:"
    echo "  systemctl start|stop|restart|status ${SERVICE_NAME}"
else
    log "Skipping systemd. Start manually with:"
    echo "  source .venv/bin/activate && python3 main.py"
    echo "  # or: python3 scripts/cyber-minecraft-ai start"
fi

# ----------------------------------------------------------------- health
log "Verifying installation..."
python3 scripts/cyber-minecraft-ai doctor || true

cat <<EOF

============================================================
 Installation complete!
============================================================
 Dashboard:   http://127.0.0.1:7860  (first admin login: see
              data/admin_credentials.txt or set ADMIN_PASSWORD)
 CLI:         python3 scripts/cyber-minecraft-ai --help
 Logs:        ${LOG_FILE}
 Uninstall:   ./scripts/uninstall.sh   (asks about data retention)
============================================================
EOF
