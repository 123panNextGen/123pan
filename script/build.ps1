$ErrorActionPreference = "Stop"

$project = Resolve-Path (Join-Path $PSScriptRoot "..")

$JOBS = [Environment]::ProcessorCount
$OUT_NAME = "123pan.exe"

$NOFOLLOW = @(
  # 测试工具
  "pytest", "pylint", "mypy", "unittest", "pdb", "doctest"
  # 包管理
  "setuptools", "wheel", "pip", "distutils", "ensurepip", "venv", "zipapp"
  # GUI（未使用）
  "tkinter", "turtle", "idlelib"
  # 异步（项目纯同步）
  "asyncio"
  # 数据库（未使用）
  "sqlite3", "dbm"
  # HTTP/网络服务（通过 requests 库）
  "http.server", "http.client", "wsgiref", "cgi", "cgitb"
  # 邮件/MIME（未使用）
  "email", "mailbox", "mime", "smtplib", "poplib", "imaplib"
  # XML/HTML解析（未使用）
  "xml", "xml.etree", "xml.dom", "xml.sax", "html", "html.parser"
  # 科学计算（未使用）
  "numpy", "pandas", "matplotlib", "PIL", "scipy", "sklearn"
  # IPython/Jupyter（未使用）
  "IPython", "jupyter"
  # 性能分析
  "profile", "cProfile"
  # 终端/密码（未使用）
  "curses", "readline", "netrc", "getpass"
  # 压缩归档（运行时不需要）
  "zipfile", "tarfile", "gzip", "bz2", "lzma"
  # 命令行解析（未使用）
  "argparse", "optparse", "shlex"
  # 日志处理器（仅用基础 logging）
  "logging.handlers"
  # pickle序列化（未使用）
  "pickle", "shelve"
  # 其他未使用模块
  "pydoc", "wave", "symbol", "symtable", "tabnanny"
  "json.tool"
  "calendar", "difflib", "textwrap"
)

$nofollowStr = $NOFOLLOW -join ","

Push-Location $project
try {
  & uv run -m nuitka src/123pan.py `
    --lto=yes `
    --standalone `
    --enable-plugin=pyqt6 `
    --plugin-enable=upx `
    --jobs="$JOBS" `
    --msvc=latest `
    --static-libpython=no `
    --nofollow-import-to="$nofollowStr" `
    --assume-yes-for-downloads `
    --python-flag=no_docstrings `
    --python-flag=no_asserts `
    --python-flag=no_site `
    --noinclude-setuptools-mode=nofollow `
    --remove-output `
    --output-filename="$OUT_NAME" `
    $args

  # ============================================================
  # 清理
  # ============================================================
  $DIST_DIR = "123pan.dist"
  Write-Host "Cleaning up $DIST_DIR ..."

  # 1. 删除 Qt 翻译文件
  Get-ChildItem -Recurse -Path $DIST_DIR -Directory -Filter "translations" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

  # 2. 删除 Qt SQL 驱动（未使用数据库）
  Get-ChildItem -Recurse -Path $DIST_DIR -Directory -Filter "sqldrivers" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

  # 3. 删除不必要的 Qt 图片格式插件（保留常用格式）
  $keepImgfmt = @("qico", "qjpeg", "qpng", "qsvg", "qwebp")
  $imgfmtDirs = Get-ChildItem -Recurse -Path $DIST_DIR -Directory -Filter "imageformats" -ErrorAction SilentlyContinue
  foreach ($dir in $imgfmtDirs) {
    Get-ChildItem -Path $dir.FullName -File -ErrorAction SilentlyContinue | ForEach-Object {
      $keep = $false
      foreach ($k in $keepImgfmt) {
        if ($_.Name -like "*$k*") { $keep = $true; break }
      }
      if (-not $keep) {
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
      }
    }
  }

  # 4. 删除仅用于嵌入式设备的 EGL 显示集成（桌面不需要）
  Get-ChildItem -Recurse -Path $DIST_DIR -Filter "Qt6EglFSDeviceIntegration*" -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

  # 5. 删除 Qt PDF 模块（未使用）
  Get-ChildItem -Recurse -Path $DIST_DIR -Filter "Qt6Pdf*" -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

  # 6. 删除 .pyc 缓存和 __pycache__
  Get-ChildItem -Recurse -Path $DIST_DIR -Filter "*.pyc" -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue
  Get-ChildItem -Recurse -Path $DIST_DIR -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

  # 7. 删除导入库（.lib 运行时不需要，保留 python*.lib）
  Get-ChildItem -Recurse -Path $DIST_DIR -Filter "*.lib" -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -notlike "python*.lib" } |
    Remove-Item -Force -ErrorAction SilentlyContinue

  # 8. 删除 .dist-info 元数据目录
  Get-ChildItem -Recurse -Path $DIST_DIR -Directory -Filter "*.dist-info" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

  Write-Host "Cleanup done."

  # 打包 .dist 目录为 zip
  Compress-Archive -Path $DIST_DIR -DestinationPath "123pan-windows.zip" -Force

} finally {
  Pop-Location
}
