# Nsight Agent

[中文说明](README.zh-CN.md)

New users: follow the [step-by-step Chinese onboarding guide](docs/GETTING_STARTED.zh-CN.md), including connection checks, prompts for every tool, troubleshooting, updates and removal.

Download [v1.1.0](https://github.com/liubingjun1207/nsight-agent/releases/tag/v1.1.0): [full source with installers, examples and guides](https://github.com/liubingjun1207/nsight-agent/releases/download/v1.1.0/nsight_agent-1.1.0.tar.gz), [wheel](https://github.com/liubingjun1207/nsight-agent/releases/download/v1.1.0/nsight_agent-1.1.0-py3-none-any.whl), and [SHA256SUMS](https://github.com/liubingjun1207/nsight-agent/releases/download/v1.1.0/SHA256SUMS). Use v1.1.0 for all eighteen tools; v1.0.0 has twelve.

The [project scope](docs/PROJECT_SCOPE.zh-CN.md) retains 18 official CUDA/NVTX reports and defines the finite v1.1 extension. The [three acceptance layers](docs/ACCEPTANCE.zh-CN.md) cover numeric correctness, real model usage and installation from artifacts.

Ask Codex about CUDA kernel timing. This local MCP server calls **NVIDIA Nsight Systems**, returns structured official statistics, and lets Codex explain the evidence or drill down. It does not send raw profiling databases to the model or implement a second profiling engine.

```text
Your question → Codex → MCP tools → nsys stats → structured results → Codex
```

v1.1 adds Windows/Linux local Systems collection, recorded PyTorch eager NVTX associations and optional Compute report metrics. See [the extension guide](docs/EXTENSIONS.md) and [actual platform validation](docs/VALIDATION-v1.1.md). GUI automation, remote management, Compute collection and compiled/fused graph attribution remain excluded. No separate model API key is required by this server.

## Install and connect

Linux source users can run `bash install.sh` or use `.venv/bin/python` for the commands below. Run Codex and this STDIO server on the host owning the reports/workload; this project supplies no remote transport.

Requirements: Python 3.11+, NVIDIA Nsight Systems (tested with 2025.6.3), and a `.nsys-rep` or Nsight-exported `.sqlite`. A GPU is needed to capture the example workload, not to analyze an existing report.

From this source checkout in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m nsight_agent --setup
.\.venv\Scripts\python.exe -m nsight_agent --check-connection
```

Windows source-package users can run `powershell -File .\install.ps1` to create the environment, install, set up and check the bundled sample. `--setup` first verifies a real STDIO handshake and tool calls, then backs up and configures only nsight, requires its startup and sets 30s/600s timeouts. It installs the packaged analysis skill while preserving custom edits. Reconnect Codex afterward. `--check-connection --report <path>` additionally verifies a sample. These checks do not replace real model evaluation. Moving the environment requires rerunning setup. Quoted existing table headers fail safely; use manual configuration. The older `--configure-codex` command remains available for configuration-only setup.

Alternatively, merge the following into your Codex `config.toml`, replacing the example Python path. Do not replace unrelated configuration:

```toml
[mcp_servers.nsight]
command = 'C:\path\to\nsight-agent\.venv\Scripts\python.exe'
args = ['-m', 'nsight_agent']
enabled = true
required = true
startup_timeout_sec = 30
tool_timeout_sec = 600

[mcp_servers.nsight.env]
NSIGHT_NSYS_PATH = 'C:\Program Files\NVIDIA Corporation\Nsight Systems 2025.6.3\target-windows-x64\nsys.exe'
NSIGHT_TIMEOUT_SECONDS = '120'
PYTHONIOENCODING = 'utf-8'
```

The executable is discovered from `NSIGHT_NSYS_PATH`, PATH, then standard Windows installations. Optional `NSIGHT_CACHE_DIR` selects the cache root. Default: local app data `nsight-agent` on Windows, `~/.cache/nsight-agent` elsewhere. Each server session has an isolated cache; after stopping the server, its `session-*` folders can be removed to reclaim disk space.

The wheel includes the analysis skill; `--setup` installs it into `~/.codex/skills/`. If an existing skill is unrecognized or customized, it is preserved and reported. A required server fails Codex startup explicitly when its command is broken; fix/reinstall its Python path or remove/disable that entry. Restart/reconnect after configuration changes.

## Tools

| Tool | Official Nsight report / behavior |
| --- | --- |
| `nsight_doctor` | Version, executable, supported reports/options |
| `nsight_open_report` | Register a local report; return a session-local ID |
| `nsight_capabilities` | Discover the fixed 18 allowed reports and installed support |
| `nsight_stats` | Unified official CUDA/NVTX report invocation; see [catalog](docs/REPORTS.md) |
| `nsight_kernel_summary` | `cuda_gpu_kern_sum`: total, count, mean, median, min, max, standard deviation |
| `nsight_kernel_trace` | `cuda_gpu_trace`: kernel rows only, with start/duration/device/stream |
| `nsight_cuda_api_summary` | `cuda_api_sum`: CPU-side CUDA calls |
| `nsight_memory_summary` | `metric="time"`: `cuda_gpu_mem_time_sum`; `metric="size"`: `cuda_gpu_mem_size_sum` |
| `nsight_nvtx_summary` | `nvtx_sum`: discover Push/Pop and Start/End range aggregates |
| `nsight_nvtx_trace` | `nvtx_pushpop_trace`: individual Push/Pop ranges and reusable time windows |
| `nsight_compare` | Compare full official kernel/API/memory tables before pagination |
| `nsight_export_analysis` | Export immutable selected result pages as Markdown or JSON |
| `nsight_capture_targets` | Discover local owner-configured tasks and time limits |
| `nsight_capture` | Run bounded `nsys profile` on one configured target; register its report |
| `nsight_operator_summary` | Recorded eager operator NVTX/kernel launch associations |
| `nsight_compute_doctor` | Optional Compute installation and fixed metric catalog |
| `nsight_compute_open_report` | Register a separate `.ncu-rep` |
| `nsight_compute_metrics` | Occupancy/throughput/memory/stalls/launch metrics, units and missing data |

Systems analyses accept `report_id` and an optional `query` object. Capture and Compute parameters are described in [the extension guide](docs/EXTENSIONS.md):

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

## Analysis workflow

Discover NVTX names with `nsight_nvtx_summary`, then individual Push/Pop ranges with `nsight_nvtx_trace`. Its default order is chronological. A trace row includes `time_query` for existing analysis tools, PID/TID and nesting. Official names retain domain prefixes; `RangeId` is not an NVTX filter index. Start/End instance discovery is not supported. A CPU annotation window is not GPU completion or launch attribution.

Open baseline and candidate reports, then use `nsight_compare` with independent scopes. It supports kernel summary, CUDA API summary, memory time and memory size; exact names are matched across complete tables. Differences are candidate minus baseline, missing sides are null, and count changes are flagged. Read [the full comparison and export reference](docs/WORKFLOW-v0.2.md) or [中文流程指南](docs/WORKFLOW-v0.2.zh-CN.md).

Use `nsight_capabilities` and `nsight_stats` for launch/queue timing, API traces, grid/block grouping, mixed GPU traces and NVTX GPU projection/association. Specialized tools and the v0.2 comparison API remain compatible.

Every analysis returns a `result_id`; `nsight_export_analysis` writes selected snapshots to `<cache_dir>/exports/`. The last 100 results are retained per service session; exports persist on disk. They contain local paths and reproduction commands. Only requested pages are exported, with pagination metadata.

## Try the public sample

The repository includes NVIDIA's Linux/Tesla T4 training capture at `examples/reports/baseline_nvtx.nsys-rep`. See [provenance and license](examples/reports/README.md). The binary is excluded from the Python wheel; use the source checkout for examples.

Ask Codex (use the absolute path to your checkout):

> Open `C:\path\to\nsight-agent\examples\reports\baseline_nvtx.nsys-rep`. Show the ten most expensive CUDA kernels by cumulative time. Inspect executions of the top kernel, then repeat the summary within the `Train` NVTX range. Explain the units and percentage denominator.

See [the reproducible demo](docs/DEMO.md) and [Linux collection instructions](examples/README.md) for your own reports.

## Statistical and operational boundaries

- Nsight computes the statistics. Python parses, filters, sorts and paginates them; comparisons subtract official aggregates without recomputing their statistics.
- Time/NVTX filters include overlapping events with full durations, not clipped durations. `Time (%)` retains the official denominator before name filtering or pagination.
- Cumulative kernel time is not application wall time or GPU utilization; concurrent kernels may overlap. CPU API duration is not GPU execution time.
- No rows or missing capture data cannot establish zero activity or a root cause. Operator associations require recorded NVTX labels; full framework/fusion attribution is not provided.
- The original report is copied into an isolated cache. `.nsys-rep` is exported with `nsys export`; all `nsys stats` commands operate on the cached SQLite. Registration is lazy, so a corrupt report fails at first analysis rather than registration.
- Local profiling data stays on disk; selected result rows are returned to the connected model. No HTTP listener or telemetry is started by this service. Export files contain the selected evidence and local paths.
- Commands use fixed reports, argument arrays, a private working directory and a timeout. The service does not expose shell commands, SQL, or arbitrary report scripts. It removes report-path/Python-path overrides from the child environment.
- Pagination bounds model output, not Nsight's work: each query materializes the selected official CSV locally before sorting. Narrow large traces by time/NVTX. Cache copies require additional disk space. Queries are serialized per server.

## Real model evaluation

After signing into Codex CLI, run `python examples/evaluate_codex.py --reports-dir examples/reports --output-dir .cache/model-evaluation`. It preserves the configured model, records actual MCP events in ephemeral sessions, rejects non-Nsight fallbacks and checks requested ranges/values/exports. Review final answers as well as event checks. Use `--case core --repetitions 2` to repeat the representative flow. Raw logs remain local; do not upload auth or private reports to CI. See [acceptance criteria](docs/ACCEPTANCE.zh-CN.md).

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

CI runs GPU-free tests and builds on Windows and Linux, Python 3.11/3.13. GPU/reader validation is separate and limited to the environments recorded in [v1.1 validation](docs/VALIDATION-v1.1.md); [v1.0 results](docs/VALIDATION.md) remain historical evidence.

The service uses the [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk/tree/v1.27.0), [Codex MCP integration](https://developers.openai.com/codex/mcp), and [Nsight Systems CLI](https://docs.nvidia.com/nsight-systems/UserGuide/).

## License

Project code: [Apache-2.0](LICENSE). NVIDIA's included training capture has its own [license](examples/reports/LICENSE-NVIDIA.md). NVIDIA binaries and report scripts are not bundled. This is an independent integration, not an NVIDIA or OpenAI product.
