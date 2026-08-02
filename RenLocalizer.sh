#!/usr/bin/env bash
# RenLocalizer launcher for Linux/macOS
# Supports both:
#   1. Portable PyInstaller folder launches
#   2. Source checkout launches with auto-venv bootstrap

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_BINARY="$SCRIPT_DIR/RenLocalizer"
RUN_PY="$SCRIPT_DIR/run.py"
VENV_DIR="$SCRIPT_DIR/venv"
REQ_FILE="$SCRIPT_DIR/requirements.txt"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_info() {
    printf '%b\n' "${GREEN}[RenLocalizer]${NC} $1"
}

print_warn() {
    printf '%b\n' "${YELLOW}[RenLocalizer]${NC} $1"
}

print_error() {
    printf '%b\n' "${RED}[RenLocalizer]${NC} $1" >&2
}

run_portable_build() {
    cd "$SCRIPT_DIR"

    if [[ ! -x "$APP_BINARY" ]]; then
        chmod +x "$APP_BINARY"
    fi

    # If we're already in a software-rendering retry, just exec
    if [[ -n "${RENLOCALIZER_GL_RETRY:-}" ]]; then
        print_info "Launching portable build (software rendering)..."
        exec "$APP_BINARY" "$@"
    fi

    print_info "Launching portable build..."
    set +e  # Allow non-zero exit so we can retry with software rendering
    "$APP_BINARY" "$@"
    local exit_code=$?
    set -e

    if [[ "$exit_code" -eq 0 ]]; then
        exit 0
    fi

    # Only retry for signal-based crashes (exit > 128 means killed by signal).
    # SIGABRT (134 = 128+6) is the typical GLX failure mode.
    # Normal error exits (1–127) are handled by Python-level recovery.
    if [[ "$exit_code" -le 128 ]]; then
        exit "$exit_code"
    fi

    # Signal crash: likely a GLX / OpenGL driver abort
    print_warn "Application crashed with signal $((exit_code - 128)) (exit code $exit_code)."
    print_warn "Retrying with software rendering (QT_QUICK_BACKEND=software)..."

    export QT_QUICK_BACKEND="software"
    export RENLOCALIZER_GL_RETRY="1"
    exec "$APP_BINARY" "$@"
}

ensure_python3() {
    if ! command -v python3 >/dev/null 2>&1; then
        print_error "Python 3 is not installed."
        printf '%s\n' "Please install Python 3.10 or higher."
        printf '%s\n' "  Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
        printf '%s\n' "  Fedora: sudo dnf install python3 python3-pip"
        printf '%s\n' "  macOS: brew install python3"
        exit 1
    fi

    local python_version
    python_version="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    local python_major="${python_version%%.*}"
    local python_minor="${python_version##*.}"

    if [[ "$python_major" -lt 3 || ( "$python_major" -eq 3 && "$python_minor" -lt 10 ) ]]; then
        print_error "Python 3.10 or higher is required. Current version: Python ${python_version}"
        exit 1
    fi

    print_info "Python ${python_version} detected"
}

run_source_checkout() {
    ensure_python3

    if [[ ! -f "$RUN_PY" ]]; then
        print_error "Portable executable and source entrypoint were not found next to this launcher."
        exit 1
    fi

    cd "$SCRIPT_DIR"

    if [[ ! -d "$VENV_DIR" ]]; then
        print_warn "Setting up source environment..."
        python3 -m venv "$VENV_DIR"
        # shellcheck disable=SC1091
        source "$VENV_DIR/bin/activate"

        print_info "Upgrading pip..."
        pip install --upgrade pip >/dev/null 2>&1

        if [[ ! -f "$REQ_FILE" ]]; then
            print_error "requirements.txt not found in source checkout."
            exit 1
        fi

        print_info "Installing dependencies..."
        pip install -r "$REQ_FILE"
        print_info "Environment setup complete"
    else
        # shellcheck disable=SC1091
        source "$VENV_DIR/bin/activate"
        print_info "Virtual environment activated"
    fi

    print_info "Launching source checkout..."
    exec python3 "$RUN_PY" "$@"
}

if [[ -f "$APP_BINARY" && -d "$SCRIPT_DIR/_internal" ]]; then
    run_portable_build "$@"
else
    run_source_checkout "$@"
fi
