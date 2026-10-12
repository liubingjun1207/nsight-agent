param([string]$PythonCommand = 'python')

Set-StrictMode -Version Latest
$projectRoot = (Resolve-Path -LiteralPath $PSScriptRoot -ErrorAction Stop).Path
$environmentPython = Join-Path $projectRoot '.venv/Scripts/python.exe'

function Invoke-ProjectPython {
    param([string[]]$Arguments)
    & $environmentPython @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python step failed with exit code $LASTEXITCODE." }
}

if (-not (Test-Path -LiteralPath $environmentPython)) {
    & $PythonCommand -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11+ required'"
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11 or later first.' }
    & $PythonCommand -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}

Invoke-ProjectPython -Arguments @('-m', 'pip', 'install', $projectRoot)
Invoke-ProjectPython -Arguments @('-m', 'nsight_agent', '--setup')
$sampleReport = Join-Path $projectRoot 'examples/reports/baseline_nvtx.nsys-rep'
if (Test-Path -LiteralPath $sampleReport) {
    Invoke-ProjectPython -Arguments @('-m', 'nsight_agent', '--check-connection', '--report', $sampleReport)
} else {
    Invoke-ProjectPython -Arguments @('-m', 'nsight_agent', '--check-connection')
}
Write-Host 'Installed and checked. Reconnect Codex, then ask it to analyze the bundled sample.'
