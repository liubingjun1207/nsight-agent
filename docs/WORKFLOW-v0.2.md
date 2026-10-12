# v0.2 workflow: discover, compare, export

Install and connect using the [README](../README.md). Existing six tools keep their parameters and returned fields; analysis results additionally contain `result_id`, `recorded_at` and source metadata. Four new tools bring the total to ten.

## Discover the training window

Open `examples/reports/baseline_nvtx.nsys-rep` with `nsight_open_report`. Call `nsight_nvtx_summary` using its `report_id` to discover names without guessing. It uses official `nvtx_sum`, supports the existing `query` fields, and defaults to descending total duration.

Then call `nsight_nvtx_trace`:

```json
{"report_id":"BASELINE_ID","query":{"name_contains":"Train","limit":1}}
```

This uses `nvtx_pushpop_trace`; the default is `Start (ns)` ascending. It returns original columns (including PID, TID, nesting, RangeId and ParentId) and a `time_query` per row. Pass that object as `query` to kernel/API/memory tools to analyze the selected window. Incomplete ranges without usable integer boundaries have `time_query=null`.

Names retain Nsight's domain prefix, such as `:Train`; they are not automatically rewritten into CLI NVTX filter expressions. `RangeId` is an arbitrary official identifier, not a zero-based `--filter-nvtx` instance index. Use a returned time window or a known valid NVTX expression. Summary supports Push/Pop and Start/End; individual discovery supports Push/Pop only. No ranges does not establish that the workload had no GPU activity.

CPU annotation intervals do not measure GPU completion. Time queries select complete overlapping events, including concurrent work from other threads/devices. They do not establish launch attribution. Nested NVTX durations cannot be added to obtain application wall time.

## Compare two reports

Open the bundled `firstOptimization.nsys-rep` as the candidate. Both public tutorial captures contain `Train`. Call `nsight_compare`:

```json
{
  "baseline_report_id":"BASELINE_ID",
  "candidate_report_id":"CANDIDATE_ID",
  "kind":"kernel_summary",
  "baseline_scope":{"nvtx":"Train"},
  "candidate_scope":{"nvtx":"Train"},
  "query":{"limit":10}
}
```

Repeat with `kind="cuda_api_summary"`, `"memory_time"` and `"memory_size"`. Memory time and bytes remain separate comparisons.

| Parameter | Behavior |
| --- | --- |
| `kind` | Defaults to `kernel_summary`; the four values above are supported |
| `baseline_scope`, `candidate_scope` | Independent objects with `start_ns`, `end_ns` OR `nvtx`; omitted means the whole report |
| `query.name_contains` | Shared case-insensitive substring filter on official full names |
| `query.sort_by` | `delta_total` (default), `absolute_delta_total`, `baseline_total`, `candidate_total`, or `name` |
| `query.descending` | Defaults to true |
| `query.offset`, `query.limit` | Defaults to 0 and 20; limit 1–200 |

The service matches exact full names across complete official tables before pagination. It does not normalize case for matching, merge duplicate names or infer correspondence after kernel fusion/renaming. Duplicate names are an explicit schema error. Equal sort values are ordered by name; missing sort values come last in either direction.

Each row includes `baseline`, `candidate`, `status` (`matched`/`added`/`removed`), `changes` by official numeric column, and `count_changed`. The result also includes complete-match status counts, count-changed row count, units and both sets of commands, sources and scopes.

- Differences are candidate minus baseline. Relative percent is difference / baseline × 100.
- Zero baselines produce a null relative percent with `reason="zero_baseline"`.
- A missing side remains null, with `reason="missing_side"`; it is not a measured zero. Added/removed rows sort after measured deltas by default; use candidate/baseline total sorting to inspect them.
- Official averages/medians remain Nsight's values; the service subtracts them without re-aggregating events. Different event counts can explain changed cumulative time.
- Each `Time (%)` retains its own denominator. Its absolute difference is in percentage points, not application speedup.
- A successful comparison proves arithmetic and provenance, not equivalent work, a causal optimization or a controlled benchmark. Verify comparable inputs, ranges and hardware before interpreting changes.

## Export evidence

Use the `result_id` from any analysis or comparison:

```json
{"result_ids":["NVTX_RESULT_ID","KERNEL_COMPARE_ID","API_COMPARE_ID"],"format":"markdown"}
```

Call `nsight_export_analysis` again with `format="json"` for machine-readable evidence. Each call creates a unique file under `<cache_dir>/exports/`; it returns the absolute path and does not rerun Nsight. Markdown includes readable tables plus exact JSON evidence, including filters, columns, units, local source paths and reproduction commands. Event names are escaped in tables.

Exports contain only the selected result pages. `total_rows`, `offset` and `next_offset` identify incomplete tables; request more pages before exporting if needed. The service retains the latest 100 analysis snapshots per session. Older IDs and IDs from a restarted service fail explicitly; rerun the desired query. Export files survive service restart and may be removed manually when no longer needed. Cached SQLite paths in commands require the associated cache to remain present; the original source path and filters remain recorded.

The export contains evidence, not a new model-generated diagnosis. Review local paths before sharing the document.

## Upgrade from v0.1

Install the new wheel in the same virtual environment (or install the updated source checkout), reconnect the MCP service, and reopen reports. The six existing tools remain compatible. Refresh the optional analysis skill if you previously copied it. No Codex configuration change is needed when the Python executable path stays the same. Two report exports plus two statistics commands can take longer than a single query; for large captures keep Codex's tool timeout longer than the complete operation.

If an optional NVTX report is unavailable, that tool returns an explicit capability error; the original tools remain usable. `nsight_doctor.optional_reports` lists these optional capabilities.

See [sample provenance](../examples/reports/README.md), [Linux collection](../examples/README.md), [measured demo](DEMO.md) and [validation](VALIDATION.md).
