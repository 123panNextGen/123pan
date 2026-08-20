#!/usr/bin/env bash

#Copyright (C) 2026 123panNextGen
#[https://github.com/123panNextGen/123pan]
#
#This program is free software: you can redistribute it and/or modify
#it under the terms of the GNU General Public License as published by
#the Free Software Foundation, either version 3 of the License, or
#(at your option) any later version.

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

case "$(uname -s)" in
  Linux)
    OUT_NAME=123pan
    EXTRA_ARGS=(--clang)
    ;;
  Darwin)
    OUT_NAME=123pan
    EXTRA_ARGS=(--macos-create-app-bundle)
    ;;
  MINGW*|MSYS*|CYGWIN*)
    OUT_NAME=123pan.exe
    EXTRA_ARGS=(
      --windows-console-mode=disable
      --msvc=latest
      --static-libpython=no
    )
    ;;
  *)
    echo "不支持的构建平台: $(uname -s)" >&2
    exit 1
    ;;
esac

NOFOLLOW=(
  pytest unittest pdb doctest test
  tests tkinter turtle idlelib setuptools
  wheel pip distutils ensurepip venv zipapp
  pydoc pydoc_data http.server wsgiref cgi
  cgitb numpy pandas scipy sklearn matplotlib
  IPython jupyter profile cProfile curses
  readline PySide6.QtUiTools PySide6.QtWebEngineCore
  PySide6.QtWebEngineWidgets PySide6.QtWebEngineQuick
  PySide6.QtWebChannel PySide6.QtMultimedia
  PySide6.QtMultimediaWidgets PySide6.QtBluetooth
  PySide6.QtNfc PySide6.QtSensors PySide6.QtPositioning
  PySide6.QtSerialPort PySide6.Qt3DCore PySide6.Qt3DRender
  PySide6.Qt3DInput PySide6.Qt3DLogic PySide6.QtCharts
  PySide6.QtDataVisualization PySide6.QtHelp
  urllib3.contrib cryptography.x509 zstandard.tests
)

(
  cd "$project"

  uv run -m nuitka src/123pan.py \
    --lto=yes \
    --standalone \
    --enable-plugin=pyside6 \
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
