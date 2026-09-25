$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$distRoot = Join-Path $root "dist"
$distApp = Join-Path $distRoot "RBM"

Set-Location $root

Write-Host "== RBM build start ==" -ForegroundColor Cyan

if (Test-Path $distApp) {
    Write-Host "Removing previous dist\RBM..." -ForegroundColor Yellow
    Remove-Item $distApp -Recurse -Force
}

$python = (Get-Command python -ErrorAction Stop).Source
& $python -m PyInstaller --clean --noconfirm --name RBM --noconsole --icon=BorneCommander.ico --add-data "BorneCommander.ico;." --add-data "tools\simulator;tools\simulator" --collect-all ttkbootstrap --collect-all reportlab --collect-all paramiko --hidden-import=debug_logs --hidden-import=energy_manager --hidden-import=network_config --hidden-import=plink_backend --hidden-import=ssh_manager --hidden-import=test_sequence src/RemoteBorneManager.py

Write-Host "Copying runtime folders..." -ForegroundColor Cyan
Copy-Item "src\config" $distApp -Recurse -Force
New-Item -ItemType Directory -Path "$distApp\documents" -Force | Out-Null
foreach ($language in @("FR", "EN")) {
    $sourceFolder = Join-Path "src\documents" $language
    $targetFolder = Join-Path "$distApp\documents" $language
    $releaseDocuments = Get-ChildItem $sourceFolder -Filter "RBM_V16_*.docx" -File

    if ($releaseDocuments.Count -ne 2) {
        throw "Expected the two V16 delivery documents in $sourceFolder; found $($releaseDocuments.Count)."
    }

    New-Item -ItemType Directory -Path $targetFolder -Force | Out-Null
    Copy-Item $releaseDocuments.FullName $targetFolder -Force
}
Copy-Item "src\tools" $distApp -Recurse -Force
Copy-Item "src\imgs" $distApp -Recurse -Force


Write-Host ""
Write-Host "== Verification ==" -ForegroundColor Cyan

$checks = @(
    "RBM.exe",
    "config\config.example.ini",
    "tools\plink.exe",
    "tools\pscp.exe"
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
    throw "Expected 4 V16 delivery documents in the package; found $docCount."
}
Write-Host "Runtime configuration copied from src\config."

$imgCount = 0
if (Test-Path (Join-Path $distApp "imgs")) {
    $imgCount = (Get-ChildItem (Join-Path $distApp "imgs") -Recurse -File | Measure-Object).Count
}
Write-Host "Images copied: $imgCount"

Write-Host ""
Write-Host "RBM build completed successfully." -ForegroundColor Green
Write-Host "Output: $distApp" -ForegroundColor Green
