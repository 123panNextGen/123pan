```bash
#!/usr/bin/env bash
set -euo pipefail

project=$(realpath "$(dirname "$0")/..")

if [ "$(uname -s)" = "Linux" ]; then
  OUT_NAME=123pan
  EXTRA_ARGS=(
    --standalone
    --lto=yes
  )
else
  OUT_NAME=123pan.exe
  EXTRA_ARGS=(
    --standalone
    --windows-disable-console
    --msvc=latest
    --static-libpython=no
    --lto=yes
  )
fi

(
  cd "$project"

  uv run -m nuitka src/123pan.py \
    --enable-plugin=pyqt6 \
    --assume-yes-for-downloads \
    --python-flag=no_docstrings \
    --remove-output \
    "${EXTRA_ARGS[@]}" \
    --output-filename="$OUT_NAME" \
    "$@"
)
```
