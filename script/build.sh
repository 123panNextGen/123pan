#!/usr/bin/env bash
set -euo pipefail

project=$(realpath "$(dirname "$0")/..")

if [ "$(uname -s)" = "Linux" ]; then
  OUT_NAME=123pan
  EXTRA_ARGS=(
    --onefile
    --standalone
    --lto=yes
  )
else
  OUT_NAME=123pan.exe
  EXTRA_ARGS=(
    --onefile-no-compression
    --standalone
    --windows-console-mode=disable
    --msvc=latest
    --static-libpython=no
    --lto=yes
  )
fi

(
  cd "$project"

  uv run -m nuitka src/123pan.py \
    --enable-plugin=pyqt6 \
    --nofollow-import-to=pytest,pylint,mypy,unittest,tkinter,pydoc,setuptools,wheel,pip,distutils \
    --plugin-enable=upx \
    --assume-yes-for-downloads \
    --python-flag=no_docstrings \
    --python-flag=no_asserts \
    --noinclude-setuptools-mode=nofollow \
    --nofollow-import-to=setuptools,wheel,pip \
    --remove-output \
    "${EXTRA_ARGS[@]}" \
    --output-filename="$OUT_NAME" \
    "$@"
)