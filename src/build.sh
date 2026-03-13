#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ "$(uname -s)" = "Linux" ]; then
  OUT_NAME=123pan
  EXTRA_ARGS=(--lto=yes)
else
  OUT_NAME=123pan.exe
  EXTRA_ARGS=(--windows-disable-console --lto=yes)
fi

python -m nuitka 123pan.py \
  --onefile \
  --enable-plugin=pyqt6 \
  --assume-yes-for-downloads \
  "${EXTRA_ARGS[@]}" \
  --output-filename="$OUT_NAME"
