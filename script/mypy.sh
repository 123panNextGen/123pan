#!/usr/bin/env bash
set -euo pipefail

project=$(realpath $(dirname $0)/..)

DEFAULT_ARGS=(--disable-error-code import-not-found --follow-untyped-imports --explicit-package-bases)

(
  cd $project

  uv run mypy "${DEFAULT_ARGS[@]}" "${@:-.}"
  )
