# Windows runner. Slot values come from environment variables.
$ErrorActionPreference = "Stop"
if (-not $env:input_dir) { throw "set input_dir" }
if (-not $env:feature_query) { throw "set feature_query" }
if (-not $env:output_dir) { $env:output_dir = "./out" }
if (-not $env:extra_keywords) { $env:extra_keywords = "" }

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $py) { throw "python is required to run function-files-pack" }

$script = Join-Path $PSScriptRoot "pack_feature.py"
& $py.Source $script $env:input_dir $env:feature_query $env:output_dir $env:extra_keywords
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
