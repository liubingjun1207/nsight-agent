# Nsight Agent v1.2.0

Release date: 2026-10-13. Codex can call twenty local MCP tools, including six official Nsight Systems diagnostic rules. Existing collection, statistics, eager NVTX associations, Compute imports and evidence exports remain compatible.

## Added capabilities / 新增能力

- `nsight_analysis_rules` discovers installed support and defaults for a fixed six-rule allowlist.
- `nsight_analyze` runs `cuda_api_sync`, `cuda_memcpy_async`, `cuda_memcpy_sync`, `cuda_memset_sync`, `gpu_gaps` or `gpu_time_util` on a registered Systems report.
- Diagnostic queries support exclusive time/NVTX scope, API-name filtering where available, sorting, complete official results before pagination, bounded thresholds/chunks and reusable time_query windows.
- Diagnostics include rule/version/parameter/unit/command evidence and use existing JSON/Markdown snapshot exports. Missing capture data is distinguished from no rule findings; the service preserves SKIPPED diagnostics hidden by analyze --quiet in Systems 2025.6.3.
- Connection checks now honor local env_vars and cwd with explicit env overrides; unsupported remote executor configuration fails clearly.
- Model acceptance requires the correct start and end for first-second and first-ten-second scopes and rejects NVTX substitution.
- Bilingual diagnostic guides, twenty-tool onboarding and the packaged analysis skill explain the diagnostic-to-trace workflow.

## Install and upgrade / 安装与升级

Download the full source archive for installers, public reports, examples and guides. Extract it and run `powershell -File .\install.ps1` on Windows or `bash install.sh` on Linux. Existing users can install the wheel in the configured server's Python environment, then run `python -m nsight_agent --setup` and reconnect Codex. Customized skills are preserved.

Verify package version `1.2.0` and twenty tools with `--check-connection`; call `nsight_analysis_rules` to inspect installed rule availability. Systems 2025.6.3 is the verified diagnostic baseline. Existing-report analysis does not require a GPU or an additional model API key.

- [中文入门指南](https://github.com/liubingjun1207/nsight-agent/blob/v1.2.0/docs/GETTING_STARTED.zh-CN.md)
- [Diagnostic workflow](https://github.com/liubingjun1207/nsight-agent/blob/v1.2.0/docs/DIAGNOSTICS.md) · [中文诊断指南](https://github.com/liubingjun1207/nsight-agent/blob/v1.2.0/docs/DIAGNOSTICS.zh-CN.md)
- [Validation evidence](https://github.com/liubingjun1207/nsight-agent/blob/v1.2.0/docs/VALIDATION-v1.2.md)
- [Scope and exclusions](https://github.com/liubingjun1207/nsight-agent/blob/v1.2.0/docs/PROJECT_SCOPE.zh-CN.md)

## Verification and limits / 验证与边界

The 219 GPU-free tests cover source and installed-wheel behavior, including the two pre-release review fixes. CI checks Windows/Ubuntu and Python 3.11/3.13. Separate development validation passed 59 Windows real integrations and 21 Linux-container diagnostic integrations; the public capture's rule results were compared with direct official CLI output. One real installed-wheel Codex workflow completed fourteen MCP calls and exported nine diagnostic/trace snapshots; its archived events passed the stricter range grader.

The public Linux/Tesla T4 baseline contains 1928 synchronization records, 1926 pageable asynchronous-copy records and 954 GPU gaps above 1ms. The longest gap is 267.528328ms. The low GPU time utilization rule reports 34.3% for its coalesced whole-report region and 36.4% for Train. These are candidate diagnostic patterns, not confirmed root causes or SM utilization. The synchronous memcpy/memset rules have real no-findings coverage and positive mock-schema coverage in this validation.

GPU gaps default to a 500ms threshold. Time utilization counts GPU operation time and profiling overhead; concurrency can exceed 100%, and initial/final inactivity outside each process/device's operation span is excluded. Hardware counters require a separate Compute report. No findings is not proof of optimal performance.

Linux real validation used Debian 13.7 on Docker Desktop/WSL2, not a bare-metal training cluster. No remote management, Compute collection, UVM/IO specialty analysis, full fusion attribution or automatic optimization is added. See the validation record for exact versions and distinctions between development measurements and final package checks.

Project code is Apache-2.0. Bundled public Systems captures retain their original license. Private captures and NVIDIA Compute SDK reports are not redistributed. Release assets: installable wheel, complete source archive and SHA256SUMS.
