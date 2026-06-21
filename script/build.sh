#!/usr/bin/env bash
set -euo pipefail

project=$(realpath "$(dirname "$0")/..")

if command -v nproc &>/dev/null; then
  JOBS=$(nproc)
else
  JOBS=4
fi

OUT_NAME=123pan

NOFOLLOW=(
  # 测试工具
  pytest pylint mypy unittest pdb doctest
  # 包管理
  setuptools wheel pip distutils ensurepip venv zipapp
  # GUI（未使用）
  tkinter turtle idlelib
  # 异步（项目纯同步）
  asyncio
  # 数据库（未使用）
  sqlite3 dbm
  # HTTP/网络服务（通过 requests 库）
  http.server http.client wsgiref cgi cgitb
  # 邮件/MIME（未使用）
  email mailbox mime smtplib poplib imaplib
  # XML/HTML解析（未使用）
  xml xml.etree xml.dom xml.sax html html.parser
  # 科学计算（未使用）
  numpy pandas matplotlib PIL scipy sklearn
  # IPython/Jupyter（未使用）
  IPython jupyter
  # 性能分析
  profile cProfile
  # 终端/密码（未使用）
  curses readline netrc getpass
  # 压缩归档（运行时不需要）
  zipfile tarfile gzip bz2 lzma
  # 命令行解析（未使用）
  argparse optparse shlex
  # 日志处理器（仅用基础 logging）
  logging.handlers
  # pickle序列化（未使用）
  pickle shelve
  # 其他未使用模块
  pydoc wave symbol symtable tabnanny
  json.tool
  calendar difflib textwrap
)

(
  cd "$project"

  uv run -m nuitka src/123pan.py \
    --lto=yes \
    --standalone \
    --enable-plugin=pyqt6 \
    --plugin-enable=upx \
    --jobs="$JOBS" \
    --clang \
    --nofollow-import-to="$(IFS=,; echo "${NOFOLLOW[*]}")" \
    --assume-yes-for-downloads \
    --python-flag=no_docstrings \
    --python-flag=no_asserts \
    --python-flag=no_site \
    --noinclude-setuptools-mode=nofollow \
    --noinclude-default-mode=nofollow \
    --remove-output \
    --output-filename="$OUT_NAME" \
    "$@"

  # ============================================================
  # 清理 .dist 目录中不需要的文件，大幅减小体积
  # ============================================================
  DIST_DIR="${OUT_NAME}.dist"
  echo "Cleaning up $DIST_DIR ..."

  # 1. 删除 Qt SQL 驱动（未使用数据库）
  find "$DIST_DIR" -path "*/PyQt6/Qt6/plugins/sqldrivers" -exec rm -rf {} + 2>/dev/null || true

  # 2. 删除 Qt 网络信息插件
  find "$DIST_DIR" -path "*/PyQt6/Qt6/plugins/networkinformation" -exec rm -rf {} + 2>/dev/null || true

  # 3. 删除 Qt 翻译文件（体积很大，通常 10-20MB）
  find "$DIST_DIR" -path "*/PyQt6/Qt6/translations" -exec rm -rf {} + 2>/dev/null || true

  # 4. 删除不必要的 Qt 图片格式插件（保留常用格式）
  keep_imgfmt="qico qjpeg qpng qsvg qwebp"
  for d in $(find "$DIST_DIR" -path "*/PyQt6/Qt6/plugins/imageformats" -type d 2>/dev/null); do
    for f in "$d"/*; do
      name=$(basename "$f")
      keep=0
      for k in $keep_imgfmt; do
        case "$name" in
          *"$k"*) keep=1; break ;;
        esac
      done
      if [ "$keep" -eq 0 ]; then
        rm -f "$f"
      fi
    done
  done 2>/dev/null || true

  # 5. 删除不需要的 Qt 库（Linux .so）
  find "$DIST_DIR" -name "libQt6DBus*" -delete 2>/dev/null || true
  find "$DIST_DIR" -name "libQt6Xml*" -delete 2>/dev/null || true
  find "$DIST_DIR" -name "libQt6Test*" -delete 2>/dev/null || true
  find "$DIST_DIR" -name "libQt6Concurrent*" -delete 2>/dev/null || true

  # 6. 删除 .pyc 缓存文件
  find "$DIST_DIR" -name "*.pyc" -delete 2>/dev/null || true
  find "$DIST_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

  # 7. 删除静态库（运行时不需要）
  find "$DIST_DIR" -name "*.a" -delete 2>/dev/null || true

  # 8. 删除 .dist-info 元数据目录
  find "$DIST_DIR" -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true

  echo "Cleanup done."

  # 打包 .dist 目录为 tar.xz
  tar -cJf "${OUT_NAME}-linux.tar.xz" "$DIST_DIR"
)
