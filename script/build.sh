#!/usr/bin/env bash
set -euo pipefail

project=$(realpath "$(dirname "$0")/..")

# 注入构建信息到 const.py
COMMIT_HASH=$(git -C "${project}" rev-parse --short HEAD 2>/dev/null || echo "unknown")
BUILD_TIME=$(date -u '+%Y-%m-%d %H:%M UTC')

CONST_FILE="${project}/src/app/common/const.py"
sed -i.bak "s/^_BUILD_COMMIT = .*/_BUILD_COMMIT = \"${COMMIT_HASH}\"/" "${CONST_FILE}"
sed -i.bak "s/^_BUILD_TIME = .*/_BUILD_TIME = \"${BUILD_TIME}\"/" "${CONST_FILE}"
rm -f "${CONST_FILE}.bak"

case "$(uname -s)" in
  Linux)
    OUT_NAME=123pan-open
    EXTRA_ARGS=(--lto=yes)
    ;;
  Darwin)
    OUT_NAME=123pan-open
    EXTRA_ARGS=(--macos-create-app-bundle --lto=yes)
    ;;
  *)
    OUT_NAME=123pan-open.exe
    EXTRA_ARGS=(--windows-disable-console --lto=yes)
    ;;
esac

(
  cd "${project}"

  uv run -m nuitka src/123pan-open.py \
    --onefile \
    --enable-plugin=pyside6 \
    --assume-yes-for-downloads \
    "${EXTRA_ARGS[@]}" \
    --output-filename="${OUT_NAME}" \
    "$@"
)
