# Nsight Agent

[中文说明](README.zh-CN.md)

New users: follow the [step-by-step Chinese onboarding guide](docs/GETTING_STARTED.zh-CN.md), including connection checks, prompts for every tool, troubleshooting, updates and removal.

Ask Codex about CUDA kernel timing. This local MCP server calls **NVIDIA Nsight Systems**, returns structured official statistics, and lets Codex explain the evidence or drill down. It does not send raw profiling databases to the model or implement a second profiling engine.

```text
Your question → Codex → MCP tools → nsys stats → structured results → Codex
```

The first release targets Windows analysis of Linux captures. GUI automation, remote collection, Nsight Compute and framework-operator attribution are outside v0.1. No separate model API key is required by this server.

## Install and connect

Requirements: Python 3.11+, NVIDIA Nsight Systems (tested with 2025.6.3), and a `.nsys-rep` or Nsight-exported `.sqlite`. A GPU is needed to capture the example workload, not to analyze an existing report.

From this source checkout in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m nsight_agent --doctor
.\.venv\Scripts\python.exe -m nsight_agent --configure-codex
```

The setup command discovers Nsight, backs up the user's Codex configuration, and replaces only the `nsight` server tables. It sets 30s startup and 300s tool timeouts. Run it again after moving the installation or changing the Python environment. If the existing file uses unusual quoted table headers, it fails without writing; use manual configuration instead.

Alternatively, merge the following into your Codex `config.toml`, replacing the example Python path. Do not replace unrelated configuration:

```toml
[mcp_servers.nsight]
command = 'C:\path\to\nsight-agent\.venv\Scripts\python.exe'
args = ['-m', 'nsight_agent']
enabled = true
startup_timeout_sec = 30
tool_timeout_sec = 300

[mcp_servers.nsight.env]
NSIGHT_NSYS_PATH = 'C:\Program Files\NVIDIA Corporation\Nsight Systems 2025.6.3\target-windows-x64\nsys.exe'
NSIGHT_TIMEOUT_SECONDS = '120'
PYTHONIOENCODING = 'utf-8'
```

The executable is discovered from `NSIGHT_NSYS_PATH`, PATH, then standard Windows installations. Optional `NSIGHT_CACHE_DIR` selects the cache root. Default: local app data `nsight-agent` on Windows, `~/.cache/nsight-agent` elsewhere. Each server session has an isolated cache; after stopping the server, its `session-*` folders can be removed to reclaim disk space.

For reusable analysis guidance, copy `skills/nsight-analysis` into `~/.codex/skills/`. This is optional; the tools have their own descriptions. Restart/reconnect the MCP server after configuration changes.

## Tools

| Tool | Official Nsight report / behavior |
| --- | --- |
| `nsight_doctor` | Version, executable, supported reports/options |
| `nsight_open_report` | Register a local report; return a session-local ID |
| `nsight_kernel_summary` | `cuda_gpu_kern_sum`: total, count, mean, median, min, max, standard deviation |
| `nsight_kernel_trace` | `cuda_gpu_trace`: kernel rows only, with start/duration/device/stream |
| `nsight_cuda_api_summary` | `cuda_api_sum`: CPU-side CUDA calls |
| `nsight_memory_summary` | `metric="time"`: `cuda_gpu_mem_time_sum`; `metric="size"`: `cuda_gpu_mem_size_sum` |

Analyses accept `report_id` and an optional `query` object:

```json
{"report_id":"ID_FROM_OPEN", "query":{"name_contains":"gemm", "limit":10}}
```

Query fields:

| Field | Default / meaning |
| --- | --- |
| `start_ns`, `end_ns` | Optional report-relative time boundaries in ns; either may be omitted |
| `nvtx` | Optional `range[@domain][/index]`, zero-based instance; exclusive with time boundaries |
| `name_contains` | Case-insensitive substring of kernel/API name or memory operation |
| `sort_by` | Exact returned column label; defaults to `Total Time (ns)`, trace `Duration (ns)`, size `Total (B)` |
| `descending` | `true`; set false with `sort_by="Start (ns)"` for chronological trace |
| `offset`, `limit` | 0 and 20; limit 1–200; follow returned `next_offset` |

Results preserve NVIDIA's column names and include units, version, official report, filters, full command arguments for reproduction, total matching rows and pagination. Memory time and size are separate queries, never ambiguously joined. Unknown versions/options, missing data, malformed CSV and subprocess errors surface as MCP tool errors.

## Try the public sample

The repository includes NVIDIA's Linux/Tesla T4 training capture at `examples/reports/baseline_nvtx.nsys-rep`. See [provenance and license](examples/reports/README.md). The binary is excluded from the Python wheel; use the source checkout for examples.

Ask Codex (use the absolute path to your checkout):

> Open `C:\path\to\nsight-agent\examples\reports\baseline_nvtx.nsys-rep`. Show the ten most expensive CUDA kernels by cumulative time. Inspect executions of the top kernel, then repeat the summary within the `Train` NVTX range. Explain the units and percentage denominator.

See [the reproducible demo](docs/DEMO.md) and [Linux collection instructions](examples/README.md) for your own reports.

## Statistical and operational boundaries

- Nsight computes the statistics. Python only parses, filters names/kernel rows, sorts and paginates them.
- Time/NVTX filters include overlapping events with full durations, not clipped durations. `Time (%)` retains the official denominator before name filtering or pagination.
- Cumulative kernel time is not application wall time or GPU utilization; concurrent kernels may overlap. CPU API duration is not GPU execution time.
- No rows or missing capture data cannot establish zero activity or a root cause. Framework operators need additional attribution that v0.1 does not provide.
- The original report is copied into an isolated cache. `.nsys-rep` is exported with `nsys export`; all `nsys stats` commands operate on the cached SQLite. Registration is lazy, so a corrupt report fails at first analysis rather than registration.
- Local profiling data stays on disk; selected result rows are returned to the connected model. No HTTP listener or telemetry is started by this service.
- Commands use fixed reports, argument arrays, a private working directory and a timeout. The service does not expose shell commands, SQL, or arbitrary report scripts. It removes report-path/Python-path overrides from the child environment.
- Pagination bounds model output, not Nsight's work: each query materializes the selected official CSV locally before sorting. Narrow large traces by time/NVTX. Cache copies require additional disk space. Queries are serialized per server.

## Develop and validate

```powershell
python -m pip install -e '.[dev]'
python -m pytest -m 'not integration'
python -m ruff check .
python -m build
# Real installed Nsight + bundled Linux capture:
$env:NSIGHT_INTEGRATION = '1'
python -m pytest -m integration -v
```

CI runs GPU-free tests and builds on Windows and Linux, Python 3.11/3.13. This is not a claim of Linux runtime certification. Real Windows/Linux-report integration is a separate release gate; see [validation notes](docs/VALIDATION.md).

The service uses the [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk/tree/v1.27.0), [Codex MCP integration](https://developers.openai.com/codex/mcp), and [Nsight Systems CLI](https://docs.nvidia.com/nsight-systems/UserGuide/).

## License

Project code: [Apache-2.0](LICENSE). NVIDIA's included training capture has its own [license](examples/reports/LICENSE-NVIDIA.md). NVIDIA binaries and report scripts are not bundled. This is an independent integration, not an NVIDIA or OpenAI product.
