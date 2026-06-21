$ErrorActionPreference = "Stop"

$project = Resolve-Path (Join-Path $PSScriptRoot "..")

Push-Location $project
try {
  if ($args.Count -eq 0) {
    & uv run pylint .
  } else {
    & uv run pylint @args
  }
} finally {
  Pop-Location
}
