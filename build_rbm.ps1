$ErrorActionPreference = "Stop"

$root = "C:\Users\p126579\Documents\2-SOFT_Borne\RemoteBorne-main\RemoteBorne"
$distRoot = Join-Path $root "dist"
$distApp = Join-Path $distRoot "RBM"

Set-Location $root

Write-Host "== RBM build start ==" -ForegroundColor Cyan

if (Test-Path $distApp) {
    Write-Host "Removing previous dist\RBM..." -ForegroundColor Yellow
    Remove-Item $distApp -Recurse -Force
}

pyinstaller --clean --noconfirm --name RBM --noconsole --icon=BorneCommander.ico --add-data "BorneCommander.ico;." --collect-all ttkbootstrap --collect-all reportlab --hidden-import=debug_logs --hidden-import=energy_manager --hidden-import=network_config --hidden-import=plink_backend --hidden-import=ssh_manager src/RemoteBorneManager.py

Write-Host "Copying runtime folders..." -ForegroundColor Cyan
Copy-Item "src\config" $distApp -Recurse -Force
Copy-Item "src\documents" $distApp -Recurse -Force
Copy-Item "src\tools" $distApp -Recurse -Force
Copy-Item "src\imgs" $distApp -Recurse -Force

if (Test-Path "src\logs") {
    Copy-Item "src\logs" $distApp -Recurse -Force
}
if (Test-Path "src\exports") {
    Copy-Item "src\exports" $distApp -Recurse -Force
}

Write-Host ""
Write-Host "== Verification ==" -ForegroundColor Cyan

$checks = @(
    "RBM.exe",
    "config\config.ini",
    "tools\plink.exe",
    "tools\pscp.exe"
)

foreach ($item in $checks) {
    $full = Join-Path $distApp $item
    if (Test-Path $full) {
        Write-Host "[OK] $item" -ForegroundColor Green
    } else {
        Write-Host "[MISSING] $item" -ForegroundColor Red
    }
}

$docCount = 0
if (Test-Path (Join-Path $distApp "documents")) {
    $docCount = (Get-ChildItem (Join-Path $distApp "documents") -Recurse -File | Measure-Object).Count
}
Write-Host "Documents copied: $docCount"

$imgCount = 0
if (Test-Path (Join-Path $distApp "imgs")) {
    $imgCount = (Get-ChildItem (Join-Path $distApp "imgs") -Recurse -File | Measure-Object).Count
}
Write-Host "Images copied: $imgCount"

Write-Host ""
Write-Host "RBM build completed successfully." -ForegroundColor Green
Write-Host "Output: $distApp" -ForegroundColor Green