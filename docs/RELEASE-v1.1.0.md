# Nsight Agent v1.1.0

Release date: 2026-10-13. Codex can discover eighteen local MCP tools: the twelve existing tools plus bounded Systems collection, recorded eager operator associations and optional Compute metrics. The Systems catalog remains fixed at eighteen official CUDA/NVTX reports.

## Added capabilities / 新增能力

- `nsight_capture_targets` and `nsight_capture` run only owner-configured local tasks, with fixed CUDA/NVTX tracing, duration/timeout bounds and unique report output. Tool calls cannot supply a new command or arguments.
- `nsight_operator_summary` preserves recorded PyTorch eager NVTX/kernel launch associations. It requires collection-time labels; nested ranges may duplicate kernels.
- `nsight_compute_doctor`, `nsight_compute_open_report` and `nsight_compute_metrics` import existing `.ncu-rep` files through five fixed occupancy/throughput/memory/stalls/launch groups, retaining units, missing metrics and evidence exports.
- `install.sh` supports Linux source installation. Setup preserves venv interpreter paths and optional capture/Compute/cache environment settings.
- Configuration syntax and cache failures now provide actionable errors. Ordinary successful-command diagnostics no longer reject valid Systems statistics.

## Install and upgrade / 安装与升级

Use the source archive for both installers, public Systems reports, example workloads and full guides. Extract it, enter the project directory and run `powershell -File .\install.ps1` on Windows or `bash install.sh` on Linux. The wheel contains runtime and the packaged analysis skill; install it in your chosen Python environment, then run `python -m nsight_agent --setup` and reconnect Codex.

Package version should be `1.1.0`; the connected server should expose eighteen tools. Collection is disabled until a local task registry is configured. Compute is optional and requires its separate report reader/report. Existing Systems APIs remain compatible, and customized skills are preserved.

- [中文入门指南](GETTING_STARTED.zh-CN.md)
- [Linux/collection/Compute guide](EXTENSIONS.md) · [中文扩展指南](EXTENSIONS.zh-CN.md)
- [Validation evidence](VALIDATION-v1.1.md)
- [Fixed scope and exclusions](PROJECT_SCOPE.zh-CN.md)

## Verification and limits / 验证与边界

CI checks Windows/Ubuntu on Python 3.11/3.13, including source and installed wheels; each suite contains 159 GPU-free tests. Separately, eighteen selected Windows and eight Linux-container real integrations passed. One final Codex extension workflow completed thirteen actual MCP calls and its answer was checked against tool evidence. Exact environments and reproduction details are recorded in the validation guide.

Linux GPU validation used Debian 13 on Docker Desktop/WSL2; PyTorch eager execution was validated on Windows and its report also read on Linux. Compute 2026.1.0 imports were checked against direct official CSV. These results do not certify every training host, model or prompt.

This release provides no remote/cluster management, Compute collection, full compiled/fused graph attribution or automatic optimization. Missing data cannot be reconstructed from kernel names or treated as zero.

Project code is Apache-2.0. Public Systems captures retain their original license. Private captures and the locally installed NVIDIA Compute SDK sample are not redistributed. Assets: wheel, full source archive and SHA256SUMS.
