# Official bottleneck diagnostics (1.2.0.dev1)

This development extension adds two MCP tools and six fixed NVIDIA expert-system rules. There are twenty tools in this checkout; published v1.1.0 packages contain eighteen and lack this extension. Existing statistics, collection and Compute interfaces remain compatible. [中文指南](DIAGNOSTICS.zh-CN.md).

Install from this source checkout with `python -m pip install -e .` using the configured server's virtual-environment Python, then run `python -m nsight_agent --setup` and `--check-connection`. Reconnect Codex. Setup backs up the nsight configuration and installs the packaged analysis skill while preserving custom edits. A GPU is unnecessary for analyzing an existing report.

Connection checks read whitelisted local `env_vars` from the checker process, apply explicit `env` overrides, and pass `cwd` to the real STDIO child. Unset forwarded variables are omitted; SDK default system variables remain available. Remote executor placement/variable sources fail explicitly. The checker cannot inspect another running Codex process's environment.

`nsight_analysis_rules()` discovers installed version, availability, supported parameters and defaults. It never expands the allowlist. Open a Systems `.nsys-rep` or exported `.sqlite` first, then call `nsight_analyze(report_id, rule, query?, options?)`.

| Rule | Evidence | Parameters |
| --- | --- | --- |
| `cuda_api_sync` | Host-blocking device/stream synchronization; CPU API duration | API name/scope/page controls in query |
| `cuda_memcpy_async` | Pageable asynchronous copies; GPU copy duration | Same |
| `cuda_memcpy_sync` | Selected synchronous copies; GPU copy duration | Same; excludes some small H2D/same-device copies |
| `cuda_memset_sync` | Selected pinned/Unified Memory synchronous memset patterns; GPU duration | Same |
| `gpu_gaps` | Per-process/device gaps longer than the threshold | `options.gap_ms`: integer 0–60000, default 500 ms |
| `gpu_time_util` | Low GPU operation time utilization | `options.threshold_percent`: 0–100, default 50; `chunks`: 1–1000, default 30 |

Options are valid only for their respective rules. query uses report-relative `start_ns/end_ns` OR `nvtx=name[@domain][/index]`, never both. API `name_contains` works only for the four CUDA rules; sort columns must belong to the rule schema. Default sorting is Duration (ns) descending. Device IDs are preserved in GPU output; no device-filter API is added.

Example:

```json
{"report_id":"ID_FROM_OPEN","rule":"gpu_gaps","query":{"limit":5},"options":{"gap_ms":1}}
```

Natural-language workflow:

> Open baseline_nvtx.nsys-rep and discover official diagnostic rules and NVTX ranges. Check synchronization, pageable copies and GPU gaps with a 1ms threshold, showing at most five rows each. Follow the longest gap's returned time_query with CPU CUDA API traces. Separate candidate evidence from confirmed causes and export selected JSON evidence.

For short steps, choose a gap threshold explicitly; the default 500ms can return no findings even when shorter gaps exist. For low time utilization in Train, pass `query={"nvtx":"Train"}` to `gpu_time_util`. A first-second synchronization query uses `query={"start_ns":0,"end_ns":1000000000}`.

Results include status, version, official rule, actual parameters, filters, columns/units, reproduction arguments and exportable result_id. `findings` means filtered findings exist; an out-of-range page can still be empty. `no_findings` means no rule matches these parameters/filters, not zero activity or proof of optimality. `official_findings` precedes API name filtering; `total_rows` follows it. Missing required data raises `MISSING_DATA`; unsupported installed capabilities raise `CAPABILITY_UNAVAILABLE`. Malformed output is an error.

Rules execute with `rows=-1` before service pagination (max 200 per page), preventing the default 50-row truncation. Paging does not reduce Nsight execution cost; use time/NVTX scopes for expensive reports. Event overlap filtering can include durations outside the scope.

GPU gaps and time utilization cover each process/device's first-to-last operation span, excluding initial/final inactivity. In-Use adds GPU operation time, includes profiling overhead and can exceed 100% with concurrency. It is not SM, Tensor Core, occupancy or bandwidth utilization. Hardware counters require a separate Compute report. Findings require follow-up API/GPU/NVTX evidence, not automatic root-cause or speedup claims.

Reports are copied/exported into an isolated cache. Commands use fixed argument arrays and managed output, with a timeout and no user-supplied scripts. Analyze deliberately omits `--quiet`: 2025.6.3 otherwise hides SKIPPED missing-data states. Only the known Processing progress line is removed before CSV parsing.

Run GPU-free tests normally. Set `NSIGHT_INTEGRATION=1` to run `tests/test_diagnostics_integration.py`. For actual Codex selection and evidence, run `examples/evaluate_codex.py --reports-dir examples/reports --output-dir .cache/model-bottlenecks --case bottlenecks`. See [validation and limitations](VALIDATION-v1.2.md).
