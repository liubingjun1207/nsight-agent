# v1.1 local workflow validation

Validation date: 2026-10-12. This is new evidence for the finite v1.1 extension; [v1.0 validation](VALIDATION.md) remains a historical record. This file does not imply a GitHub Release has been published.

## Environments and measured behavior

| Environment | Evidence |
| --- | --- |
| Windows 11, Python 3.13.5, RTX 4060 Laptop GPU, driver 617.42 | Systems 2025.6.3 local collection; CUDA/NVTX annotated PyTorch 2.6.0+cu124 eager forward/backward; official NVTX/kernel association matched |
| Debian 13.7 container, Python 3.11.17, Docker Desktop 29.8.2 on WSL2 kernel 6.18.33.2 | Actual Systems 2025.6.3 Linux executable; public Linux report analysis; real CUDA driver workload collection; 18-tool STDIO handshake and analysis |
| Compute 2026.1.0 readers on Windows and Linux | Five metric groups imported from the installed NVIDIA `uncoalescedGlobalAccesses/addConstDouble.ncu-rep` sample and checked against direct official CSV |

The Linux environment is a GPU-enabled Debian container on Windows/WSL2, not a bare-metal Ubuntu training cluster. The CUDA/PyTorch eager workload was executed on Windows; Linux also read its annotated report, but this is not certification of arbitrary Linux PyTorch models or compiled graphs. Compute values describe the SDK capture, not the current machine's performance. The SDK Compute binary/report are not redistributed by this repository.

The public Systems baseline still reports the same top kernel: 1,266,481,454 ns over 938 instances. A newly collected Linux `fill_int` report contains exactly 20 launches and the driver example verifies checksum 523776. Its measured cumulative time was 16,353 ns in one capture; this timing is illustrative and not a stable benchmark expectation.

The Windows eager capture produced 36 annotated range/kernel groups. Rows preserve `aten::` labels, shapes/op IDs when present, PID/TID, counts and official durations. Repeated/nested association is not unique operator GPU time.

The SDK Compute sample contained 6 occupancy metrics, 4 throughput metrics, 5 memory metrics, 10 stall metrics and 5 launch metrics from the allowlist. Respectively 0, 2, 1, 10 and 0 requested metric names were absent. Values and units matched direct imports. For example, Windows displayed achieved active-warp occupancy as 73.53%; Linux displayed additional decimal precision. The service preserves each reader's official representation rather than asserting identical formatting across platforms.

## Automated and real checks

- 159 GPU-free tests cover the original workflow plus task bounds/registration, command selection, failure without registering partial captures, metric units/precision/missing values, filters/pagination, changed reports, optional Compute absence, evidence exports and venv interpreter preservation.
- 18 selected Windows real integration checks passed: the original kernel/API/memory/range/STDIO/setup workflow and all eight extension checks. This is not a rerun of every historical optional integration.
- All 8 Linux real extension checks passed: local collection, reading the annotated eager report, five Compute groups and the extended STDIO workflow.
- The Linux source installer was run in a fresh venv with an isolated CODEX_HOME. The final configured command must retain `.venv/bin/python`, not resolve its symlink to the base interpreter. Setup/check-connection confirm 18 tools and the sample's expected top kernel.

Reproduce GPU-free tests:

```bash
python -m pytest -m 'not integration'
python -m ruff check .
python -m build
```

Reproduce extension integration after configuring a local workload and generating `operator_workload.py`'s report:

```bash
export NSIGHT_INTEGRATION=1
export NSIGHT_CAPTURE_CONFIG=/absolute/capture-targets.toml
export NSIGHT_CAPTURE_TARGET=operator-example
export NSIGHT_OPERATOR_REPORT=/absolute/annotated.nsys-rep
export NSIGHT_COMPUTE_REPORT=/absolute/addConstDouble.ncu-rep
python -m pytest tests/test_extensions_integration.py -v
```

Use equivalent PowerShell environment assignments on Windows. These variables are local test inputs, not a permission to register executable commands through MCP. Additional real Systems checks live in `tests/test_integration.py`.

## Real Codex usage

The installed v1.1 wheel was exercised with Codex CLI 0.162.0-alpha.17.2 and the user's configured gpt-6.1-sol. One final extension run completed 13 actual MCP calls, including all six new tools plus capability discovery, kernel timing and export. It collected the requested task once, used its returned ID for eager associations, imported all five Compute groups, and exported six selected evidence pages to JSON.

The final answer was checked for numeric/unit agreement, recorded operator identity, missing metrics, nested-range double counting, replay limitations and no invented cross-capture match. No shell, SQL, web or code-edit fallback was used. Safe aggregate results are in [evaluation-results-v1.1.json](evaluation-results-v1.1.json); raw events and private paths remain in ignored local cache.

An earlier development run was stopped after an import-parameter incompatibility was found: `--apply-rules` is rejected with `--import` by Compute 2026.1.0. The final implementation uses a fixed raw CSV import and disables user config, without passing collection-only options. The clean final model run and repeated affected integrations use that corrected implementation. Counts here refer to the final checks, not a guarantee of every model or prompt.

To repeat the extension model test:

```bash
python examples/evaluate_codex.py --reports-dir examples/reports \
  --output-dir .cache/model-evaluation --case extensions \
  --capture-target operator-example --compute-report /absolute/sample.ncu-rep
```

The CLI requires NSIGHT_CAPTURE_CONFIG and an existing Compute report. It reuses the local Codex login and current model, never copies authentication into CI, and excludes the capture case from default evaluations unless explicitly selected.

## Limits

One Systems version, one Compute version, one Windows GPU and one Linux container environment were validated. No remote/cluster operation, Compute collection, complete fusion attribution, automatic optimization or broad platform certification is claimed. New capture timings can vary. Missing metrics and unannotated operators require suitable new data, not model inference.
