# Builds Shiftbase.exe (PyInstaller, one-folder) into D:\Claude\Launchables\Shiftbase.
# Everything, including caches and work files, stays on D:.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$out = "D:\Claude\Launchables"
$cache = "D:\Claude\.cache"
$env:PIP_CACHE_DIR = "$cache\pip"
$env:npm_config_cache = "$cache\npm"
$py = "$repo\.venv\Scripts\python.exe"
$env:PYTHONPATH = "$repo\backend"   # lets --collect-submodules import the Django apps

Push-Location "$repo\frontend"; npm install --no-audit --no-fund; npm run build; Pop-Location
& $py -m pip install -q -r "$repo\launcher\requirements.txt" -r "$repo\backend\requirements.txt"

$hidden = @("config", "core", "people", "scheduling", "leave", "attendance", "notifications", "reports") |
    ForEach-Object { "--collect-submodules", $_ }
& $py -m PyInstaller --noconfirm --clean --name Shiftbase --console `
    --distpath $out --workpath "$cache\pyi-work" --specpath "$cache\pyi-spec" `
    --paths "$repo\backend" @hidden `
    --collect-all rest_framework --collect-data tzdata --collect-submodules environ `
    --hidden-import whitenoise.middleware --hidden-import django.contrib.sessions.backends.db `
    --add-data "$repo\frontend\dist;frontend_dist" `
    "$repo\launcher\shiftbase_launcher.py"
Write-Host "Built: $out\Shiftbase\Shiftbase.exe"
