#!/usr/bin/env bash
set -euo pipefail

project=$(realpath "$(dirname "$0")/..")

if [ "$(uname -s)" = "Linux" ]; then
  OUT_NAME=123pan
  EXTRA_ARGS=(
    --plugin-enable=upx
  )
else
  OUT_NAME=123pan.exe
  EXTRA_ARGS=(
    --windows-console-mode=disable
    --msvc=latest
    --static-libpython=no
  )
fi

(
  cd "$project"

  uv run -m nuitka src/123pan.py \
    --lto=yes \
    --onefile \
    --standalone \
    --enable-plugin=pyqt6 \
    --nofollow-import-to=pytest,pylint,mypy,unittest,tkinter,pydoc,setuptools,wheel,pip,distutils \
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
