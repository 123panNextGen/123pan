#!/usr/bin/env bash
set -euo pipefail

# 检测目标架构；CI 通过 BUILD_ARCH 环境变量传入，本地构建从 uname -m 推断
if [ -n "${BUILD_ARCH:-}" ]; then
  ARCH="$BUILD_ARCH"
else
  case "$(uname -m)" in
    aarch64|arm64) ARCH=arm64 ;;
    *) ARCH=x64 ;;
  esac
fi

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
    --onefile-no-compression
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

# UPX 不支持 ARM64 Windows PE 文件，仅在 x64 上启用
if [ "$ARCH" = "x64" ]; then
  UPX_ARGS=(--plugin-enable=upx)
else
  UPX_ARGS=()
fi

(
  cd "$project"

  uv run -m nuitka src/123pan.py \
    --lto=yes \
    --onefile \
    --standalone \
    --enable-plugin=pyqt6 \
    "${UPX_ARGS[@]}" \
    --jobs="$JOBS" \
    --nofollow-import-to="$(IFS=,; echo "${NOFOLLOW[*]}")" \
    --assume-yes-for-downloads \
    --python-flag=no_docstrings \
    --python-flag=no_asserts \
    --python-flag=no_site \
    --noinclude-setuptools-mode=nofollow \
    --remove-output \
    "${EXTRA_ARGS[@]}" \
    --output-filename="$OUT_NAME" \
    "$@"
)
