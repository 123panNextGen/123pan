$ErrorActionPreference = "Stop"

$project = Resolve-Path (Join-Path $PSScriptRoot "..")

$defaultArgs = @(
  "--disable-error-code", "import-not-found"
  "--follow-untyped-imports"
  "--explicit-package-bases"
)

Push-Location $project
try {
  if ($args.Count -eq 0) {
    & uv run mypy @defaultArgs .
  } else {
    & uv run mypy @defaultArgs @args
  }
} finally {
  Pop-Location
}
