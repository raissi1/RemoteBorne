$ErrorActionPreference = "Stop"

$python = "C:\Users\p126579\AppData\Local\Programs\Python\Python39\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = (Get-Command python -ErrorAction Stop).Source
}

try {
    & $python -c "import paramiko"
} catch {
    Write-Host "Paramiko is required for the RBM local simulator."
    Write-Host "Install it with: $python -m pip install -r $PSScriptRoot\requirements.txt"
    exit 1
}

& $python "$PSScriptRoot\rbm_local_evse_simulator.py"
