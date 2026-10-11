# Nsight Agent

[English](README.md)

第一次使用请先阅读 [中文入门指南](docs/GETTING_STARTED.zh-CN.md)：从零安装、验证连接、六个工具的提问示例、故障排查、更新和卸载。

让 Codex 通过 MCP 调用 **Nsight Systems 官方统计命令**，分析 CUDA kernel 执行时间、CUDA API 和内存操作。模型选择分析步骤、解释结果，原始报告交给 Nsight 处理。

首版：Windows 分析 Linux 采集的报告。暂不包含 GUI 自动操作、远程采集、Nsight Compute 或 PyTorch 算子归因。

## 安装与接入 Codex

需要 Python 3.11+、Nsight Systems（已在 2025.6.3 上验证）。分析现成报告不需要 GPU；生成示例需要 CUDA GPU 和对应 PyTorch。

在项目目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m nsight_agent --doctor
.\.venv\Scripts\python.exe -m nsight_agent --configure-codex
```

接入命令会备份 Codex 配置，只更新 `nsight` 服务，并设置 30 秒启动超时、300 秒工具超时。也可使用 [英文说明中的配置片段](README.md#install-and-connect) 手动配置。`NSIGHT_NSYS_PATH` 可覆盖自动发现，`NSIGHT_TIMEOUT_SECONDS` 默认 120 秒，`NSIGHT_CACHE_DIR` 可指定缓存目录。配置后重新连接 MCP 服务。

可选：把 `skills/nsight-analysis` 复制到 `~/.codex/skills/`，供 Codex 自动选用分析指引。

## 使用

仓库附带 NVIDIA 官方 Linux/Tesla T4 报告，可直接对 Codex 说：

> 打开项目里的 examples/reports/baseline_nvtx.nsys-rep，找出累计耗时最高的十个 CUDA kernel。查看第一名的单次执行明细，再按 Train NVTX 范围统计，并解释时间单位和百分比含义。

首次调用 `nsight_open_report` 返回报告 ID，再调用：

| 工具 | 用途 |
| --- | --- |
| `nsight_doctor` | 检查安装、版本和命令能力 |
| `nsight_kernel_summary` | kernel 总耗时、次数、平均值、中位数、最小/最大值 |
| `nsight_kernel_trace` | 单次执行时间、设备和 stream |
| `nsight_cuda_api_summary` | CPU 侧 CUDA API 耗时 |
| `nsight_memory_summary` | `metric="time"` 查耗时，`metric="size"` 查字节数 |

筛选、排序和分页参数放在 `query` 中：

```json
{"report_id":"上一步返回的ID", "query":{"name_contains":"gemm", "limit":10}}
```

- `start_ns` / `end_ns`：报告时间轴的纳秒区间；可只填一个。
- `nvtx`：`范围名[@域名][/序号]`，序号从 0 开始；不能与时间区间同时填写。
- `name_contains`：名称包含匹配，不区分大小写。
- `sort_by`：使用结果中的完整列名；例如 `Start (ns)`。`descending=false` 为升序。
- `offset` / `limit`：默认 0 / 20，每页最多 200 行，按 `next_offset` 继续查询。

完整接口、错误处理及运行限制见 [英文说明](README.md)。

## 正确理解结果

Nsight 完成统计，服务只整理返回结果。时间范围筛选包含与区间重叠的完整事件；百分比沿用 Nsight 原始分母，不随名称筛选和分页重新计算。累计 kernel 时间不等于应用总耗时或 GPU 利用率，CPU API 时间也不等于 GPU 执行时间。

每次返回包含 Nsight 版本、官方报告名、单位、筛选条件和可复现命令。缺失数据会说明或报错，不解释为零。首版不依据时间相关性直接断言瓶颈原因。

原报告保持不变，服务在独立缓存中复制、导出并分析。停止服务后可以清理缓存中的 `session-*` 文件夹。分页限制模型收到的数据量；Nsight 本地仍需完成对应统计，大型 trace 建议先限定时间/NVTX。

## 示例与验证

- [公开样例来源与许可](examples/reports/README.md)
- [自行采集 Linux 报告](examples/README.md)
- [可复现演示](docs/DEMO.md)
- [验证记录](docs/VALIDATION.md)

```powershell
python -m pip install -e '.[dev]'
python -m pytest -m 'not integration'
$env:NSIGHT_INTEGRATION = '1'
python -m pytest -m integration -v
```

项目代码使用 Apache-2.0；NVIDIA 样例保留独立许可证。未打包 NVIDIA 软件或其统计脚本。此项目是独立集成。
