# Validation record — v0.2.0

Date: 2026-10-12 (Asia/Shanghai).

Environment: Windows, Python 3.13, Nsight Systems `2025.6.3.343-256337165561v0`.

A fresh isolated environment installed the release wheel with MCP SDK 1.30.0 and Pydantic 2.14.1; all 70 tests passed in 112.73 seconds, including the real STDIO workflow. Imports were verified to resolve to the installed wheel rather than the source checkout.

54 GPU-free tests and 16 real integration tests pass (70 total). Ruff and analysis-skill validation pass. Real integration compares direct CLI output with parsed MCP/service results, including both public Linux captures.

## Evidence and boundaries

- Existing five CUDA statistics, time/NVTX filtering, SQLite input and source preservation remain covered.
- Official `nvtx_sum` and `nvtx_pushpop_trace` output is checked column by column; discovered Train boundaries feed an actual kernel query.
- Kernel/API/memory-time/memory-size comparisons across both captures' Train ranges are checked against independently parsed direct CLI tables.
- Real STDIO exercises discovery, comparisons and JSON export. Exported results retain exact values and provenance.
- Synthetic tests cover more than 200 rows before matching/pagination, zero baselines, missing sides, changed counts, exact names, duplicate rejection, missing optional reports, nested/multithread NVTX records, incomplete boundaries, Unicode paths/text, snapshot expiry and a failed candidate query without partial results. Existing subprocess failure/timeout and configuration tests remain active.

The public reports are unchanged NVIDIA training artifacts. Baseline SHA-256: `760052039bd392c997fdf2533a97292825121dfe818e18f1fd6b127e79ffedea`; candidate SHA-256: `d81a008bdccd386cd1a382b49f87e90ff5bbd729bd036a9bbe11d24fa1c06980`. Nsight's metadata identifies Linux and Tesla T4. See [provenance and retained license](../examples/reports/README.md).

The new `compare_workload.py` baseline and candidate were also run locally with CUDA-enabled PyTorch on Windows; both printed checksum `104536.750000`. This verifies executable sample behavior, not Linux collection or an optimization claim. Linux capture commands are supplied for users with that environment; the public Linux report pair provides the Windows reader validation.

## Repeat

```powershell
python -m pip install -e '.[dev]'
python -m ruff check .
$env:NSIGHT_INTEGRATION = '1'
python -m pytest -q
python -m build
```

Without `NSIGHT_INTEGRATION=1`, real tests explicitly skip. GPU-free CI covers Windows/Linux and Python 3.11/3.13. Real Windows integration and an installed-wheel workflow are release gates.

This checks one Nsight reader version and two public Linux captures; it does not certify every collector version, runtime platform, multi-GPU workload or Start/End instance trace. Missing NVTX support is optional and does not disable v0.1 tools. GUI automation, Nsight Compute and framework attribution are outside this release.

Historical v0.1 validation remains available in the `v0.1.0` Git tag. Publication targets GitHub; PyPI publication is separate.
