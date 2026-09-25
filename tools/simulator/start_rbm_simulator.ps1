$ErrorActionPreference = "Stop"

$python = $env:RBM_PYTHON
$pythonArgs = @()

if (-not $python) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $python = $pythonCommand.Source
    } else {
        $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
        if ($pyLauncher) {
            $python = $pyLauncher.Source
            $pythonArgs = @("-3")
        }
    }
}

if (-not $python) {
    throw "Python 3 was not found. Install Python 3 or set RBM_PYTHON to its executable path."
}

try {
    & $python @pythonArgs -c "import paramiko"
} catch {
    Write-Host "Paramiko is required for the RBM local simulator."
    Write-Host "Install it with: $python $pythonArgs -m pip install -r $PSScriptRoot\requirements.txt"
    exit 1
}

& $python @pythonArgs "$PSScriptRoot\rbm_local_evse_simulator.py"
