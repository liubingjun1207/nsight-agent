#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_python="$project_root/.venv/bin/python"
if [[ ! -x "$project_python" ]]; then
    "${PYTHON_COMMAND:-python3}" -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"'
    "${PYTHON_COMMAND:-python3}" -m venv "$project_root/.venv"
fi
"$project_python" -m pip install "$project_root"
"$project_python" -m nsight_agent --setup
if [[ -f "$project_root/examples/reports/baseline_nvtx.nsys-rep" ]]; then
    "$project_python" -m nsight_agent --check-connection --report "$project_root/examples/reports/baseline_nvtx.nsys-rep"
else
    "$project_python" -m nsight_agent --check-connection
fi
echo 'Installed and checked. Reconnect Codex; collection requires an explicit local target registry.'
