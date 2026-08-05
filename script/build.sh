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

#不要随便动NOFOLLOW和nuitka参数，会引发非常多的问题
NOFOLLOW=(
  pytest unittest pdb doctest test
  tests tkinter turtle idlelib setuptools
  wheel pip distutils ensurepip venv zipapp
  pydoc pydoc_data http.server wsgiref cgi
  cgitb numpy pandas scipy sklearn matplotlib
  IPython jupyter profile cProfile curses
  readline PyQt6.uic PyQt6.QtWebEngine
  PyQt6.QtWebEngineCore PyQt6.QtWebEngineWidgets
  PyQt6.QtWebChannel PyQt6.QtMultimedia
  PyQt6.QtMultimediaWidgets PyQt6.QtBluetooth
  PyQt6.QtNfc PyQt6.QtSensors PyQt6.QtPositioning
  PyQt6.QtSerialPort PyQt6.Qt3DCore PyQt6.Qt3DRender
  PyQt6.Qt3DInput PyQt6.Qt3DLogic PyQt6.QtCharts
  PyQt6.QtDataVisualization PyQt6.QtHelp
  urllib3.contrib cryptography.x509 zstandard.tests
)

(
  cd "$project"

  uv run -m nuitka src/123pan.py \
    --lto=yes \
    --standalone \
    --enable-plugin=pyqt6 \
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
