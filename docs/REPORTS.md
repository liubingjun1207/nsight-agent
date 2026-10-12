# Official report catalog

The fixed 18 CUDA/NVTX reports callable through `nsight_stats`. `nsight_capabilities` checks local availability; captured data is validated at query time.

| Report | Purpose | Default sort | Default direction | Name options |
| --- | --- | --- | --- | --- |
| `cuda_api_sum` | CPU CUDA API timing summary, including synchronization | `Total Time (ns)` | descending | none |
| `cuda_api_trace` | Individual CPU CUDA API calls with correlation IDs | `Start (ns)` | ascending | none |
| `cuda_api_gpu_sum` | Combined CPU API/GPU kernel/memory categories; keep Category distinct | `Total Time (ns)` | descending | nvtx-name, base, mangled |
| `cuda_gpu_kern_sum` | Cumulative GPU kernel duration/counts | `Total Time (ns)` | descending | nvtx-name, base, mangled |
| `cuda_gpu_kern_gb_sum` | Kernel duration grouped by grid and block configuration | `Total Time (ns)` | descending | nvtx-name, base, mangled |
| `cuda_gpu_sum` | GPU kernel/memcpy/memset category summary | `Total Time (ns)` | descending | nvtx-name, base, mangled |
| `cuda_gpu_trace` | Chronological GPU kernel AND memory operations | `Start (ns)` | ascending | nvtx-name, base, mangled |
| `cuda_gpu_mem_time_sum` | GPU memcpy/memset timing | `Total Time (ns)` | descending | none |
| `cuda_gpu_mem_size_sum` | GPU memcpy/memset bytes | `Total (B)` | descending | none |
| `cuda_kern_exec_sum` | Kernel CPU launch/queue/GPU execution summary | `TAvg (ns)` | descending | nvtx-name, base, mangled |
| `cuda_kern_exec_trace` | Individual kernel CPU launch, queue and GPU execution phases | `API Start (ns)` | ascending | nvtx-name, base, mangled |
| `nvtx_sum` | Push/Pop and Start/End CPU NVTX range summary | `Total Time (ns)` | descending | none |
| `nvtx_pushpop_sum` | Push/Pop CPU NVTX range summary | `Total Time (ns)` | descending | none |
| `nvtx_pushpop_trace` | Individual Push/Pop CPU ranges with nesting and reusable windows | `Start (ns)` | ascending | none |
| `nvtx_startend_sum` | Start/End CPU range summary; no individual trace support | `Total Time (ns)` | descending | none |
| `nvtx_gpu_proj_sum` | NVTX GPU projection versus original CPU range duration | `Total Proj Time (ns)` | descending | none |
| `nvtx_gpu_proj_trace` | Individual NVTX GPU projection and original CPU range timestamps | `Projected Start (ns)` | ascending | none |
| `nvtx_kern_sum` | Kernels grouped by enclosing NVTX range and PID/TID | `Total Time (ns)` | descending | base, mangled |

## Unified call

```json
{"report_id":"ID","report":"cuda_kern_exec_trace","query":{"name_contains":"gemm","limit":5}}
```

All existing query fields are supported. `descending` defaults to the catalog direction when omitted. Name matching uses the listed name columns, including both kernel and range names for `nvtx_kern_sum`. GPU trace includes memory events; the dedicated kernel trace excludes them.

```json
{"report_id":"ID","report":"cuda_gpu_kern_gb_sum","query":{"limit":5},"options":{"name_format":"base","annotate_nvtx":true}}
```

`name_format` is `demangled` (default), `base` or `mangled`; `annotate_nvtx` defaults false. Options are accepted only when both the fixed catalog and installed report support them. Raw mangled names require compatible capture data; Nsight may fall back to demangled names for old captures. No custom scripts, SQL or shell arguments are accepted.

Output retains official columns, units, source and reproduction commands. Unsupported schema/version/parameters, missing data and process failure carry error codes and recovery guidance. Missing data is not zero; a successful empty table/name filter means no matching recorded rows.

Cache filesystem failures return `CACHE_IO_ERROR` with guidance to check permissions/free space or change `NSIGHT_CACHE_DIR`. Ordinary stderr diagnostics from successful commands are retained in `warnings`, including their command arguments. Explicit ERROR/FATAL, Python traceback and SKIPPED diagnostics still fail the call; CSV/schema validation remains mandatory. The known successful `stats --help-reports` exit status of 1 follows the same diagnostic rules.

## Interpret correctly

Launch total durations can overlap phases. Null queue time can mean execution began before the API returned. Queueing is not automatically a bottleneck.

NVTX GPU projection is the first-to-last associated GPU span, not summed activity or utilization. Association uses CPU launch calls inside same-thread NVTX ranges. NVTX/kernel groups can double-count nested ranges.

CPU API duration, GPU duration, cumulative duration and application elapsed time remain distinct. Each percentage keeps its official denominator. Existing comparison remains limited to the four v0.2 summary kinds.

[Final scope](PROJECT_SCOPE.zh-CN.md) · [Acceptance](ACCEPTANCE.zh-CN.md) · [Workflow](WORKFLOW-v0.2.md)
