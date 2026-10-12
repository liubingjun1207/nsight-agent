# Reproducible tool-call demo

This demo uses the unmodified public NVIDIA Linux report in `examples/reports/baseline_nvtx.nsys-rep`, analyzed on Windows with Nsight Systems 2025.6.3. The values below are measured from that artifact, not illustrative numbers.

## 1. Open a report

Call `nsight_open_report` with its absolute path:

```json
{"path":"C:\\path\\to\\nsight-agent\\examples\\reports\\baseline_nvtx.nsys-rep"}
```

Use the returned `report_id` in subsequent calls. IDs depend on the local file and server session; `REPORT_ID` below is a placeholder.

## 2. Find the expensive kernels

Call `nsight_kernel_summary`:

```json
{"report_id":"REPORT_ID","query":{"limit":2}}
```

The report contains 50 grouped kernel names. The largest cumulative-duration row is the `cudnn::cnn::wgrad_alg0_engine<...>` kernel:

| Official column | Result |
| --- | ---: |
| Total Time (ns) | 1,266,481,454 |
| Instances | 938 |
| Avg (ns) | 1,350,193.4 |
| Med (ns) | 1,346,098.5 |
| Min (ns) | 780,665 |
| Max (ns) | 1,551,088 |
| Time (%) | 24.9 |

This is about 1.266 seconds accumulated across 938 executions, representing 24.9% of all kernel durations summed by Nsight. It is not 24.9% GPU utilization or 24.9% of application elapsed time.

## 3. Drill into executions

Call `nsight_kernel_trace`:

```json
{"report_id":"REPORT_ID","query":{"name_contains":"wgrad_alg0_engine","sort_by":"Start (ns)","descending":false,"limit":5}}
```

Each row includes start, duration, device and stream. The whole capture contains 140,917 kernel executions; memory operations are excluded from this tool. Use a returned start/duration to select a time interval for a follow-up query.

## 4. Restrict the analysis

Call `nsight_kernel_summary` within the named training range:

```json
{"report_id":"REPORT_ID","query":{"nvtx":"Train","limit":1}}
```

The same kernel retains 1,266,481,454 ns and 938 executions, but its share becomes 25.6% because Nsight's range-filtered denominator changes.

Or query the first ten seconds of the report timeline:

```json
{"report_id":"REPORT_ID","query":{"start_ns":0,"end_ns":10000000000,"limit":1}}
```

The leading row has 918,473,440 ns across 679 executions. The service formats the CLI boundary as `10.000000000s` to avoid Nsight 2025.6's overflow for large bare-nanosecond arguments. Returned units remain nanoseconds.

## 5. Inspect supporting evidence

Use `nsight_cuda_api_summary` with `query.name_contains="Synchronize"` to inspect CPU-side synchronization calls. Call `nsight_memory_summary` once with `metric="time"` and once with `metric="size"` for memory operation time and bytes.

These observations can motivate further investigation, but do not by themselves establish whether a workload is compute-, memory-, or CPU-bound.

## Verify

Every result includes `provenance.executable` and `provenance.arguments`, which reproduce the official statistics using the cached SQLite. For a separate manual check:

```powershell
& 'C:\Program Files\NVIDIA Corporation\Nsight Systems 2025.6.3\target-windows-x64\nsys.exe' stats --report cuda_gpu_kern_sum --format 'csv:time=ns:bytes=B' --output - --quiet 'C:\path\to\baseline_nvtx.nsys-rep'
```

Unlike the MCP service's isolated cache, this manual command may create an SQLite export alongside the supplied file. The integration tests compare all returned numeric fields with independently parsed direct CLI output and exercise the real MCP stdio transport.

## 6. v0.2: discover the window and compare two captures

Use `nsight_nvtx_summary` with `query.name_contains="Train"`, then `nsight_nvtx_trace` with the same filter. The baseline's Push/Pop `:Train` range starts at 9,629,695 ns and ends at 13,870,341,778 ns. Its `time_query` can be passed directly to kernel/API/memory analyses. It is a CPU annotation window, not GPU completion.

Open `examples/reports/firstOptimization.nsys-rep` as candidate. Compare the two known `Train` NVTX ranges:

```json
{
  "baseline_report_id":"BASELINE_ID",
  "candidate_report_id":"CANDIDATE_ID",
  "kind":"kernel_summary",
  "baseline_scope":{"nvtx":"Train"},
  "candidate_scope":{"nvtx":"Train"},
  "query":{"name_contains":"wgrad_alg0_engine<float, (int)512","limit":1}
}
```

These values were measured with Nsight Systems 2025.6.3:

| Metric in Train | Baseline | Candidate | Candidate − baseline |
| --- | ---: | ---: | ---: |
| Selected wgrad kernel cumulative GPU time (ns) | 1,266,481,454 | 514,207,039 | −752,274,415 (−59.40%) |
| Selected wgrad execution count | 938 | 938 | 0 |
| Selected wgrad average GPU time (ns) | 1,350,193.4 | 548,195.1 | −801,998.3 |
| cudaDeviceSynchronize CPU time (ns) | 45,885 | 50,322 | +4,437 (+9.67%) |
| Host-to-Device copy time (ns) | 32,691,810 | 32,132,186 | −559,624 (−1.71%) |
| Host-to-Device bytes | 188,640,000 | 188,640,000 | 0 |

The complete Train comparisons match 41 kernel names, 11 CUDA API names and 3 memory-operation names. All corresponding counts are equal in this pair; added/removed and differing-count behavior is also covered by synthetic tests. Some metrics improve while others increase. These are measured differences between public tutorial captures, not a claim of controlled causal speedup.

NVTX `Train` CPU annotation duration is 13,860,712,083 ns in baseline and 8,814,677,730 ns in candidate; this is distinct from cumulative GPU kernel time.

Repeat comparison using `kind="cuda_api_summary"`, `"memory_time"`, and `"memory_size"`. Save their returned result IDs and export:

```json
{"result_ids":["KERNEL_RESULT_ID","API_RESULT_ID","MEMORY_TIME_RESULT_ID","MEMORY_SIZE_RESULT_ID"],"format":"markdown"}
```

Repeat with `format="json"`. Both exports retain the exact selected-page evidence, sources and commands. See [the full workflow](WORKFLOW-v0.2.md) or [中文流程](WORKFLOW-v0.2.zh-CN.md) for pagination, missing-side and upgrade behavior.
