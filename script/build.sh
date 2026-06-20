#!/usr/bin/env bash
set -euo pipefail

project=$(realpath "$(dirname "$0")/..")

if command -v nproc &>/dev/null; then
  JOBS=$(nproc)
elif command -v sysctl &>/dev/null; then
  JOBS=$(sysctl -n hw.ncpu)
else
  JOBS=4
fi

if [ "$(uname -s)" = "Linux" ]; then
  OUT_NAME=123pan
  EXTRA_ARGS=(
    --clang
  )
else
  OUT_NAME=123pan.exe
  EXTRA_ARGS=(
    --windows-console-mode=disable
    --msvc=latest
    --static-libpython=no
  )
fi

NOFOLLOW=(
  pytest pylint mypy unittest pdb doctest
  setuptools wheel pip distutils ensurepip venv zipapp
  pydoc
  tkinter turtle idlelib
  asyncio
  sqlite3
  http.server wsgiref cgi cgitb
  numpy pandas matplotlib PIL scipy sklearn
  IPython jupyter
  profile cProfile
  curses readline netrc getpass
)

(
  cd "$project"

  uv run -m nuitka src/123pan.py \
    --lto=yes \
    --onefile \
    --standalone \
    --enable-plugin=pyqt6 \
    --plugin-enable=upx \
    --jobs="$JOBS" \
    --nofollow-import-to="$(IFS=,; echo "${NOFOLLOW[*]}")" \
    --assume-yes-for-downloads \
    --python-flag=no_docstrings \
    --python-flag=no_asserts \
    --python-flag=no_annotations \
    --python-flag=no_site \
    --noinclude-setuptools-mode=nofollow \
    --remove-output \
    "${EXTRA_ARGS[@]}" \
    --output-filename="$OUT_NAME" \
    "$@"
)
