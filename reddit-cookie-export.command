#!/bin/zsh
set -eu

BUNDLE_DIR=${0:A:h}
TOOL_STATE=${II_REDDIT_COOKIE_EXPORT_HOME:-"$HOME/ii/ii-reddit-cookie-export"}
VENV_DIR="$TOOL_STATE/venv"
PYTHON_BIN="$VENV_DIR/bin/python"
COMMAND_BIN="$VENV_DIR/bin/ii-reddit-cookie-export"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This Reddit cookie exporter currently supports macOS only." >&2
  exit 1
fi

mkdir -p "$TOOL_STATE"
chmod 700 "$TOOL_STATE"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Preparing the Reddit cookie exporter for this Mac..."
  python3 -m venv "$VENV_DIR"
fi

if [[ ! -x "$COMMAND_BIN" ]]; then
  echo "Installing the Reddit cookie exporter locally..."
  "$PYTHON_BIN" -m pip install --disable-pip-version-check "$BUNDLE_DIR"
fi

export PYTHONDONTWRITEBYTECODE=1
exec "$COMMAND_BIN" "$@"
