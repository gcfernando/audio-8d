# Developed by ::> Gehan Fernando

# Builds bin\Audio8D-<version>-windows-x86_64.zip through build_release.py
param([switch]$Zip, [switch]$SkipCheck)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
# -Zip is kept for older instructions; the ZIP is always made now
$arguments = @((Join-Path $root "packaging\build_release.py"))
if ($SkipCheck) { $arguments += "--skip-check" }
python @arguments
if ($LASTEXITCODE -ne 0) { throw "The build failed; see the message above." }
