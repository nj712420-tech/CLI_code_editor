#!/usr/bin/env bash
# truecode installer - creates venv and installs dependencies
# Usage: ./install.sh [--dev] [--venv PATH] [--python PYTHON]

set -euo pipefail

# Default values
VENV_DIR=".venv"
INSTALL_DEV=false
PYTHON_CMD="${PYTHON:-python3}"
SKIP_VENV=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dev)
            INSTALL_DEV=true
            shift
            ;;
        --venv)
            VENV_DIR="$2"
            shift 2
            ;;
        --python)
            PYTHON_CMD="$2"
            shift 2
            ;;
        --skip-venv)
            SKIP_VENV=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--dev] [--venv PATH] [--python PYTHON] [--skip-venv]"
            echo "  --dev          Install development dependencies (pytest, ruff, mypy)"
            echo "  --venv PATH    Virtual environment directory (default: .venv)"
            echo "  --python PY    Python executable to use (default: python3)"
            echo "  --skip-venv    Skip venv creation, install in current environment"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="${REPO_ROOT}/${VENV_DIR}"

echo "=== truecode installer ==="
echo "Repo root: ${REPO_ROOT}"
echo "Venv dir:  ${VENV_PATH}"
echo "Python:    ${PYTHON_CMD}"
echo "Dev deps:  ${INSTALL_DEV}"
echo ""

# Check Python version
if ! command -v "${PYTHON_CMD}" &> /dev/null; then
    echo "Error: ${PYTHON_CMD} not found in PATH"
    exit 1
fi

PY_VERSION=$("${PYTHON_CMD}" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Python version: ${PY_VERSION}"

# Create virtual environment
if [[ "${SKIP_VENV}" == "false" ]]; then
    if [[ -d "${VENV_PATH}" ]]; then
        echo "Virtual environment already exists at ${VENV_PATH}"
    else
        echo "Creating virtual environment..."
        "${PYTHON_CMD}" -m venv "${VENV_PATH}"
    fi

    # Determine pip and python paths
    if [[ "$(uname -s)" == "MINGW"* ]] || [[ "$(uname -s)" == "CYGWIN"* ]] || [[ "$(uname -s)" == "MSYS"* ]]; then
        # Windows
        PIP="${VENV_PATH}/Scripts/pip.exe"
        PY="${VENV_PATH}/Scripts/python.exe"
    else
        # Unix/Linux/macOS
        PIP="${VENV_PATH}/bin/pip"
        PY="${VENV_PATH}/bin/python"
    fi
else
    PIP="${PYTHON_CMD} -m pip"
    PY="${PYTHON_CMD}"
fi

# Upgrade pip
echo "Upgrading pip..."
${PIP} install --upgrade pip

# Install package in editable mode
echo "Installing truecode in editable mode..."
INSTALL_CMD="${PIP} install -e ."
if [[ "${INSTALL_DEV}" == "true" ]]; then
    INSTALL_CMD="${PIP} install -e .[dev]"
fi

${INSTALL_CMD}

echo ""
echo "✅ Installation complete!"
echo ""

if [[ "${SKIP_VENV}" == "false" ]]; then
    echo "To activate the virtual environment:"
    if [[ "$(uname -s)" == "MINGW"* ]] || [[ "$(uname -s)" == "CYGWIN"* ]] || [[ "$(uname -s)" == "MSYS"* ]]; then
        echo "  ${VENV_DIR}\\Scripts\\activate"
    else
        echo "  source ${VENV_DIR}/bin/activate"
    fi
    echo ""
fi

echo "To run the app:"
echo "  truecode shell          # Interactive TUI"
echo "  truecode chat \"prompt\"  # One-shot request"
echo "  truecode --help         # Show all commands"
echo ""
echo "For development:"
echo "  ruff check aide/        # Lint"
echo "  ruff format aide/       # Format"
echo "  mypy aide/              # Type check"
echo "  pytest tests/           # Run tests"