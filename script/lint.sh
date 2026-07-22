#!/usr/bin/env bash

#Copyright (C) 2026 123panNextGen
#[https://github.com/123panNextGen/123pan]
#
#This program is free software: you can redistribute it and/or modify
#it under the terms of the GNU General Public License as published by
#the Free Software Foundation, either version 3 of the License, or
#(at your option) any later version.

set -euo pipefail

project=$(realpath $(dirname $0)/..)

(
  cd $project

  uv run pylint "$@"
  )
