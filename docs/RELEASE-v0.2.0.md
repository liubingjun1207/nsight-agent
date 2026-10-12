# Nsight Agent v0.2.0

Discover training ranges, compare baseline/candidate performance and export reproducible evidence from Codex using official Nsight Systems statistics.

## What's new / 新增能力

- `nsight_nvtx_summary`: discover NVTX names, styles, counts and durations.
- `nsight_nvtx_trace`: inspect Push/Pop instances, nesting and reusable time windows.
- `nsight_compare`: compare kernel, CUDA API, memory-time and memory-size statistics across independently selected ranges.
- `nsight_export_analysis`: export selected result snapshots as Markdown or JSON, including sources, filters, units and reproduction commands.
- Two licensed public NVIDIA Linux/Tesla T4 captures, a baseline/candidate workload and bilingual workflow documentation.

The existing six tools remain compatible. Comparisons use complete official tables before pagination, match exact names, flag changed counts, and retain missing/zero-baseline distinctions. Cumulative-time changes are not application speedup. NVTX instance discovery supports Push/Pop; Start/End remains summary-only.

## Start here / 开始使用

Validation: 70 tests passed from a freshly installed wheel, including 16 real Nsight integration checks against the public Linux captures.

- [中文安装指南](GETTING_STARTED.zh-CN.md)
- [中文 v0.2 流程指南](WORKFLOW-v0.2.zh-CN.md)
- [English workflow and API reference](WORKFLOW-v0.2.md)
- [Measured demo](DEMO.md)
- [Validation record](VALIDATION.md)

Download `nsight_agent-0.2.0.tar.gz` for the full source, guides and both reports. The wheel includes the runtime package only. SHA256SUMS lists asset hashes.

Upgrade in the existing virtual environment, reconnect the MCP service and reopen reports. Refresh the optional analysis skill if installed. Analysis result IDs last for the current session's latest 100 results; exported files remain on disk.

Project code is Apache-2.0. NVIDIA samples retain their separate license. Windows analysis of Linux reports is the validated runtime; GPU-free CI on Linux does not certify its Nsight runtime. No GUI automation, remote collection, Nsight Compute or framework attribution is included.
