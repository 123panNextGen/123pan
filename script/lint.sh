#!/usr/bin/env bash
set -euo pipefail

project=$(realpath $(dirname $0)/..)

(
  cd $project

  if (($# == 0)); then
    uv run pylint src tests
  else
    uv run pylint "$@"
  fi
)
