$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$distRoot = Join-Path $root "dist"
$distApp = Join-Path $distRoot "RBM"

Set-Location $root

Write-Host "== RBM build start ==" -ForegroundColor Cyan

# Prefer the project environment even when the caller forgot to activate it.
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if ($env:RBM_PYTHON) {
    $python = $env:RBM_PYTHON
} elseif (Test-Path $venvPython) {
    $python = $venvPython
} else {
    $python = (Get-Command python -ErrorAction Stop).Source
}
Write-Host "Python: $python"
& $python -c "import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] < (3, 15) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "Use Python 3.10-3.14 (recommended: 3.12) in .venv. This Python version is unsupported for this build."
}
& $python -c "import PyInstaller, ttkbootstrap, reportlab, paramiko"
if ($LASTEXITCODE -ne 0) {
    throw "Missing build dependencies. Run: & '$python' -m pip install -r requirements.txt"
}
& $python -B scripts/pre_commit_quality_gate.py
if ($LASTEXITCODE -ne 0) {
    throw "Quality gate failed. Build stopped; the previous portable version is unchanged."
}

# Build and verify in staging; preserve the previous portable version on error.
$finalApp = $distApp
$distStage = Join-Path $distRoot ".rbm-staging"
if (Test-Path $distStage) { Remove-Item $distStage -Recurse -Force }
$distApp = Join-Path $distStage "RBM"

& $python -m PyInstaller --clean --noconfirm --distpath $distStage --name RBM --noconsole --icon=BorneCommander.ico --add-data "BorneCommander.ico;." --add-data "tools\simulator\rbm_local_evse_simulator.py;tools\simulator" --collect-all ttkbootstrap --collect-all reportlab --collect-all paramiko --hidden-import=diagnostic_capture --hidden-import=debug_logs --hidden-import=energy_manager --hidden-import=gridcodes_migrator --hidden-import=gridcodes_migration_ui --hidden-import=network_config --hidden-import=plink_backend --hidden-import=setpoint_validation --hidden-import=ssh_manager --hidden-import=test_sequence src/RemoteBorneManager.py

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed. Build stopped; the previous portable version is unchanged."
}
if (!(Test-Path (Join-Path $distApp "RBM.exe"))) {
    throw "PyInstaller did not produce RBM.exe. No runtime files were copied."
}

Write-Host "Copying runtime folders..." -ForegroundColor Cyan
$configTarget = Join-Path $distApp "config"
New-Item -ItemType Directory -Path $configTarget -Force | Out-Null
Copy-Item "src\config\config.example.ini" $configTarget -Force
Copy-Item "BorneCommander.ico" $distApp -Force
New-Item -ItemType Directory -Path "$distApp\documents" -Force | Out-Null
foreach ($language in @("FR", "EN")) {
    $sourceFolder = Join-Path "src\documents" $language
    $targetFolder = Join-Path "$distApp\documents" $language
    $releaseDocuments = Get-ChildItem $sourceFolder -Filter "RBM_V17_*.docx" -File

    if ($releaseDocuments.Count -ne 2) {
        throw "Expected the two V17 delivery documents in $sourceFolder; found $($releaseDocuments.Count)."
    }

    New-Item -ItemType Directory -Path $targetFolder -Force | Out-Null
    Copy-Item $releaseDocuments.FullName $targetFolder -Force
}
Copy-Item "src\tools" $distApp -Recurse -Force
# `src\tools` replaces the tools folder created by PyInstaller. Restore the
# bundled simulator afterwards so the executable can start it at runtime.
$simulatorSource = Join-Path $root "tools\simulator"
$simulatorTarget = Join-Path $distApp "tools\simulator"
if (!(Test-Path (Join-Path $simulatorSource "rbm_local_evse_simulator.py"))) {
    throw "Simulator source is missing: $simulatorSource"
}
New-Item -ItemType Directory -Path $simulatorTarget -Force | Out-Null
Copy-Item (Join-Path $simulatorSource "rbm_local_evse_simulator.py") $simulatorTarget -Force
Copy-Item "src\imgs" $distApp -Recurse -Force


Write-Host ""
Write-Host "== Verification ==" -ForegroundColor Cyan

$checks = @(
    "RBM.exe",
    "config\config.example.ini",
    "tools\plink.exe",
    "tools\pscp.exe",
    "tools\simulator\rbm_local_evse_simulator.py"
)

$missingChecks = @()
foreach ($item in $checks) {
    $full = Join-Path $distApp $item
    if (Test-Path $full) {
        Write-Host "[OK] $item" -ForegroundColor Green
    } else {
        Write-Host "[MISSING] $item" -ForegroundColor Red
        $missingChecks += $item
    }
}
if ($missingChecks.Count -gt 0) {
    throw "Build output is incomplete: $($missingChecks -join ', ')"
}

$docCount = 0
if (Test-Path (Join-Path $distApp "documents")) {
    $docCount = (Get-ChildItem (Join-Path $distApp "documents") -Recurse -File | Measure-Object).Count
}
Write-Host "Documents copied: $docCount"
if ($docCount -ne 4) {
    throw "Expected 4 V17 delivery documents in the package; found $docCount."
}
Write-Host "Clean configuration template copied; personal credentials are not packaged."

$imgCount = 0
if (Test-Path (Join-Path $distApp "imgs")) {
    $imgCount = (Get-ChildItem (Join-Path $distApp "imgs") -Recurse -File | Measure-Object).Count
}
Write-Host "Images copied: $imgCount"

Write-Host ""
if (Test-Path $finalApp) {
    $backup = "$finalApp-backup-$(Get-Date -Format 'yyyyMMdd-HHmmss-fff')"
    Move-Item $finalApp $backup
    Write-Host "Previous portable version preserved: $backup"
}
Move-Item $distApp $finalApp
Remove-Item $distStage -Recurse -Force
$distApp = $finalApp
Write-Host "RBM build completed successfully." -ForegroundColor Green
Write-Host "Output: $distApp" -ForegroundColor Green
