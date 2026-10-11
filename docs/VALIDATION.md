# Validation record

Date: 2026-10-11 (Asia/Shanghai).

Environment: Windows, Python 3.13.5, official MCP Python SDK 1.27.0, Nsight Systems `2025.6.3.343-256337165561v0`.

Result: **41 tests passed** (32 GPU-free checks, 9 real integration checks), including real MCP stdio calls with structured results, configuration backup/preservation and consistent setup timeouts. Ruff and skill validation passed.

## Real capture provenance

The bundled NVIDIA report has SHA-256 `760052039bd392c997fdf2533a97292825121dfe818e18f1fd6b127e79ffedea`. Nsight's own `export --type=info` metadata identifies Ubuntu 18.04.5 LTS, the Linux Nsight Systems 2021.4.1 collector, and Tesla T4. The Windows 2025.6.3 reader successfully exports this older capture.

All five official reports were checked against direct Nsight output: kernel summary, GPU trace with kernel-only selection, CUDA API summary, memory time summary, memory size summary. Additional checks cover NVTX `Train`, a 0–10 second time filter, SQLite input, name filtering, source hash preservation and a real MCP client/server stdio workflow.

The example PyTorch workload was separately captured and analyzed locally on Windows / RTX 4060 Laptop GPU / PyTorch 2.6.0+cu124. This local artifact stays in ignored `.cache/`; it is not presented as a Linux capture.

## Repeat the checks

```powershell
python -m pip install -e '.[dev]'
python -m ruff check .
$env:NSIGHT_INTEGRATION = '1'
python -m pytest -q
python -m build
```

Without `NSIGHT_INTEGRATION=1`, real-Nsight tests skip explicitly. CI performs GPU-free tests and packaging only. The real integration suite must pass before a release is considered validated for Windows analysis of Linux reports.

Compatibility fixes discovered through real execution include: the report-list command's successful exit code 1; export timestamp checks avoided through explicit cached exports; large nanosecond argument overflow avoided with unit-qualified time strings; and subprocess stdin isolation from the MCP transport.

## Limits

This checks one installed Nsight reader version and one public Linux capture. It does not certify every capture version, multi-GPU workload, or runtime platform. No GUI automation or visual timeline test is claimed. The package is prepared for GitHub release; PyPI publication is a separate operation. Local Codex registration and successful real tool calls were verified after the initial implementation.
