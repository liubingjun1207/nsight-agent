# Nsight Agent v0.1.0

Use Codex to call NVIDIA Nsight Systems and analyze CUDA kernel timing, launch traces, CUDA API calls and memory operations. Nsight performs the statistics; the MCP service returns structured evidence for the model to explain.

## Start here / 开始使用

- 中文用户：[从零安装与使用指南](GETTING_STARTED.zh-CN.md)
- English: [installation and tool reference](../README.md)
- [Reproducible demo](DEMO.md) using the included public NVIDIA Linux/Tesla T4 report.

The source archive includes documentation, tests, the sample workload, the public report and its license. The Python wheel includes the runtime package only.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m nsight_agent --doctor
.\.venv\Scripts\python.exe -m nsight_agent --configure-codex
```

Reconnect/restart Codex MCP after configuring it, then ask it to analyze your local report.

## Scope and validation

Windows analysis of existing Linux `.nsys-rep` or exported SQLite reports; tested with Nsight Systems 2025.6.3. No GUI automation, remote collection, Nsight Compute or framework-operator attribution in this release.

Real integration compares results against Nsight CLI output and exercises MCP stdio calls. See [validation details](VALIDATION.md). Project code is Apache-2.0; the NVIDIA sample retains its separate license.
