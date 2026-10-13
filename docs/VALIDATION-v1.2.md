# v1.2 diagnostic validation

Release version: 1.2.0. Validation date: 2026-10-13. Functional measurements and model evaluation below were collected with 1.2.0.dev1; the release changes version metadata and documentation, retaining the verified implementation. The final release artifacts are checked separately below.

Windows 11 / Python 3.13.5 / Nsight Systems 2025.6.3 were used to analyze the licensed public Linux/Tesla T4 capture `examples/reports/baseline_nvtx.nsys-rep`. Source report SHA256 remains `760052039bd392c997fdf2533a97292825121dfe818e18f1fd6b127e79ffedea`. No original reports were modified.

| Official rule | Whole-report result |
| --- | --- |
| cuda_api_sync | 1928 host-blocking synchronization records |
| cuda_memcpy_async | 1926 pageable asynchronous-copy records |
| cuda_memcpy_sync | No findings in this capture |
| cuda_memset_sync | No findings in this capture |
| gpu_gaps, default gap=500ms | No findings |
| gpu_gaps, gap=1ms | 954 gaps; longest 267528328ns |
| gpu_time_util, threshold=50, chunks=30 | One coalesced low-time-utilization region, In-Use 34.3% |

Default CLI row limit is 50; service rows=-1 retrieves full results before paging. The Train NVTX scope returns In-Use 36.4%. These are the official operation-time calculations, not SM occupancy or system-wide GPU utilization.

The 21 real integration checks cover six rules across full report, first-second time filter and Train NVTX filter, plus threshold/pagination/follow-up, real missing data and STDIO/evidence export. CSV rows match a separate execution of the exact official command. Positive synchronous memcpy/memset output schemas are covered by mock fixtures; this public capture does not provide positive findings for those two rules.

A minimal SQLite without CUDA runtime events establishes missing-data handling: analyze --quiet returns empty output with exit 0, whereas the same command without quiet retains SKIPPED. The service deliberately omits quiet and maps SKIPPED to MISSING_DATA. Empty successful CSV after the known progress line is no_findings. Unrecognized or malformed output raises an error.

201 GPU-free tests passed, including the prior 159 tests, 41 diagnostic tests and one additional model-evidence grading test. They cover all six schemas, integer precision, values over 100%, full results before pagination, zero matches, name filters, bounds, unsupported installed capabilities, original-file protection, no-result exports, missing data, warnings, errors, timeout and safe progress-line handling. Ruff passed; source and wheel packages build successfully.

## Installed artifacts and real model workflow

The built wheel was installed into the existing Windows Codex server environment (MCP 1.30.0), and its actual configured-server connection discovered all twenty tools and matched the unchanged sample top kernel (1266481454ns / 938 calls). The packaged skill was updated locally with a backup of its prior managed content. A fresh Windows environment installed the wheel and passed all 201 GPU-free tests. Its real regression run passed 59 checks (38 original Systems checks and all 21 new diagnostic checks); one optional locally generated Start/End capture test was skipped. The regression covered the original eighteen report schemas, parameters, range filtering, comparison, setup and STDIO.

Codex CLI 0.162.0-alpha.17.2 / gpt-6.1-sol / Python 3.13.5 completed one real installed-wheel evaluation with 14 MCP calls. It discovered capabilities and NVTX, ran all six rules, selected 1ms gaps, queried Train time utilization and first-second synchronization, followed the longest gap window with a CPU API trace and exported nine result snapshots. No shell, SQL, web or file-edit fallback occurred. The answer was reviewed against the exported numbers, units, filters and actual API timestamps. Regrading the events also verified the diagnostic/trace result IDs were present in the actual export. Safe aggregate evidence is in [evaluation-results-v1.2.json](evaluation-results-v1.2.json); raw events and local source paths remain ignored.

The longest gap's CPU API trace contains cudaDeviceSynchronize (24285ns) and cudaMemcpyAsync (1026821ns). The model correctly stated that the short synchronization does not explain the whole 267.528328ms gap and that the copy crosses the selected boundary. It did not claim an established root cause or measured application speedup.

## Linux diagnostic validation

A fresh python:3.11-slim Debian container on Docker Desktop 29.8.2/WSL2 installed the same wheel and used the actual bundled Nsight Systems 2025.6.3 Linux executable. All 201 GPU-free tests and all 21 real diagnostic tests passed, including POSIX Processing-line parsing, time/NVTX filters, full counts, missing-data handling, twenty-tool STDIO and evidence exports. No GPU access or additional collection was needed for this existing-report diagnostic extension. The environment was Python 3.11.17, Debian 13.7 and WSL2 kernel 6.18.33.2-microsoft-standard-WSL2.

This remains container validation on Windows/WSL2, not bare-metal cluster certification. No new Compute, remote collection, UVM/IO or compiled/fused operator domain was added. The synchronous memcpy/memset rules have real no-findings coverage and positive mock schema coverage, not a claim of positive real findings in the bundled capture. One model/capture workflow is evidence of actual usability, not a guarantee for all prompts.

## Pre-release review corrections

Two reproducible review issues were fixed in the same development version. Connection checks now pass configured cwd to the STDIO child and forward locally whitelisted env_vars before applying explicit env overrides. Local object-form env_vars are also supported; unsupported remote placement/sources and invalid environment configuration fail explicitly. Values come from the checker process's environment, not another running Codex process. SDK default system environment forwarding remains in effect.

The first-second bottleneck evaluation and the first-ten-second core evaluation now require start_ns=0 and the exact requested end_ns, with no NVTX override. New regressions reject a last-one-nanosecond interval, a missing start and a conflicting NVTX scope. The archived 14-call real Codex run was regraded under these stricter checks and still passed; no new model run was claimed.

The expanded Windows GPU-free suite passed 219 tests (18 new regression cases). Actual STDIO regressions prove an env_vars invalid Nsight path fails and a relative launcher in a Chinese cwd receives its forwarded variable. The earlier Linux 201-test/21-integration and Windows 59-integration records above precede this review fix; they are historical validation, not a rerun of the updated suite.

## Final v1.2.0 package checks

The release source and wheel were built with version 1.2.0. A fresh Windows/Python 3.13 environment installed the wheel from its artifact path (not an editable checkout) and passed all 219 GPU-free tests and all 21 real diagnostic integrations against Systems 2025.6.3. An isolated CODEX_HOME setup installed the packaged skill, configured the service and passed an actual twenty-tool connection check plus the public baseline's top kernel (1266481454ns / 938 instances). No source report was modified.

The final release uses the same runtime implementation as the reviewed development build, apart from version metadata. Its updated guides describe twenty tools and link to the v1.2.0 assets. Artifact contents, source protection and checksums are verified before upload. Release CI checks the final commit's source and installed wheel across Windows/Ubuntu and Python 3.11/3.13; the exact GitHub run is visible in the repository Actions history. This record does not claim a new real model run or a rerun of every old optional GPU integration.

Reproduce:

```bash
python -m pytest -m 'not integration'
NSIGHT_INTEGRATION=1 python -m pytest tests/test_diagnostics_integration.py -q
python examples/evaluate_codex.py --reports-dir examples/reports --output-dir .cache/model-bottlenecks --case bottlenecks
```

Use PowerShell environment assignments on Windows. Model evaluation needs local Codex login. Raw reports/cache/events remain local and ignored; no authentication is copied into CI.
