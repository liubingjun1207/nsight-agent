# Nsight Agent v1.0.0

The fixed CUDA/NVTX analysis scope is complete: Codex can discover and invoke 18 official Nsight Systems reports, with existing dedicated tools, report comparison and evidence exports preserved.

## Capabilities

- `nsight_capabilities` lists allowed reports, installed support, sorting and name options.
- `nsight_stats` covers launch/queue phases, API traces, grid/block grouping, GPU memory traces and NVTX GPU projection/association.
- Report-specific validation, error codes and recovery guidance keep missing data distinct from zero measurements.
- `--setup` verifies a real local STDIO connection, backs up and configures Codex, and installs the packaged skill. `--check-connection` verifies the actual configured environment.
- `install.ps1` creates a Windows environment, installs the source package and validates the included sample.

## Verification and boundaries

See the [measured validation record](VALIDATION.md) for actual test counts, model/client versions, repeated workflow results and installation checks. SDK connection checks and real model evaluations are separate conclusions. Raw model logs and login data remain local.

Windows analysis with Nsight Systems 2025.6.3 is the validated reader baseline. The public Linux captures lack Start/End ranges; the missing-data path and a separate local Windows Start/End sample are both verified. Installed report support does not guarantee capture data or success for all prompts.

The scope is frozen: GUI automation, remote capture, Nsight Compute and framework attribution remain outside this project. Further work is maintenance unless scope is explicitly changed.

## Install and use / 开始使用

Download the full source archive for the installer, public reports and guides; the wheel contains runtime plus the analysis skill. Run `install.ps1`, or install the wheel and run `python -m nsight_agent --setup`. Reconnect Codex afterward. Existing custom skills are preserved.

- [中文入门指南](GETTING_STARTED.zh-CN.md)
- [18-report reference](REPORTS.md)
- [最终范围](PROJECT_SCOPE.zh-CN.md)
- [真实流程与安装验收](ACCEPTANCE.zh-CN.md)
- [Reproducible demo](DEMO.md)

Required MCP startup deliberately reports broken commands instead of continuing without Nsight; fix the Python path or remove/disable its configuration to recover. The older configuration-only setup and ten v0.2 tools remain compatible.

Project code: Apache-2.0. The two public NVIDIA captures retain their own license. GitHub assets include wheel, full source, installer and SHA256SUMS.
