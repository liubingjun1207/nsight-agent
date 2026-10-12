# v1.1：本地采集、Linux 与可选 Compute

范围扩展日期：2026-10-12。原来的十二个分析工具保留，新增六个工具，合计十八个。Systems 仍限定十八种官方统计报告。

## 1. 在 Linux 训练主机上安装

在同一主机安装 Python 3.11+、Nsight Systems 和 Codex CLI/IDE 环境。CLI 需要在 PATH 中，或者设置其绝对路径：

```bash
export NSIGHT_NSYS_PATH=/opt/nvidia/nsight-systems/target-linux-x64/nsys
export NSIGHT_CACHE_DIR="$HOME/.cache/nsight-agent"
bash install.sh
```

也可手动安装：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m nsight_agent --setup
.venv/bin/python -m nsight_agent --check-connection --report examples/reports/baseline_nvtx.nsys-rep
```

重新连接 MCP 后，应发现十八个工具。配置默认写入 `~/.codex/config.toml`；设置了 `CODEX_HOME` 时使用该目录。绝对报告路径必须属于 MCP 服务所在主机。[Codex 官方 MCP 说明](https://developers.openai.com/codex/mcp)

Windows 仍可运行 `powershell -File install.ps1`。Linux 同机采集和分析不需要把报告拷到 Windows。Windows 客户端连接远端服务器、SSH、集群调度不属于本版功能。

## 2. 登记一个受控采集任务

服务默认不开放采集任务。用户在本机创建 TOML 文件，登记实际可运行的命令；模型只能选择任务名，不能提交新的命令或参数。

```toml
[targets.operator-example]
description = "三轮带 NVTX 算子标注的 PyTorch eager 示例"
command = ["/absolute/project/.venv/bin/python", "/absolute/project/examples/operator_workload.py"]
cwd = "/absolute/project"
duration_seconds = 30
timeout_seconds = 120
```

`command[0]` 和 `cwd` 必须使用绝对路径。示例 Python 必须已安装支持 CUDA 的 PyTorch；服务本身不依赖 PyTorch。Windows 路径可以写成 `C:/absolute/project/...`。所有参数在这个由用户维护的文件中固定，不由工具调用追加。

设置文件位置，然后重新执行 setup：

```bash
export NSIGHT_CAPTURE_CONFIG=/absolute/project/capture-targets.toml
.venv/bin/python -m nsight_agent --setup
```

Windows 对应：

```powershell
$env:NSIGHT_CAPTURE_CONFIG = 'C:/absolute/project/capture-targets.toml'
.\.venv\Scripts\python.exe -m nsight_agent --setup
```

setup 将此变量写入 Nsight MCP 的环境配置，升级时保留已有 `NSIGHT_CAPTURE_CONFIG`、`NSIGHT_NCU_PATH` 和 `NSIGHT_CACHE_DIR`。修改登记文件后下次调用会重新读取；修改其位置后需重新配置并重连。

对 Codex 说：

> 列出已登记的采集任务。运行 operator-example，分析生成报告中最耗时的十个 CUDA kernel，再查看 aten::mm 对应的 kernel 关联。

调用顺序为 `nsight_capture_targets` → `nsight_capture(target_id="operator-example")` → 使用返回的 `report_id` 分析。报告存入独立 `capture-*` 缓存目录，不覆盖原报告。

采集固定启用 `cuda,nvtx`，关闭 CPU 采样和上下文切换。采集时长为 1–120 秒，命令超时为 30–300 秒，且至少比采集时长多 15 秒。到达时长限制会终止启动的应用；超时会清理此调用启动的进程树。只登记可重跑、允许采样中止的任务，应用自身可能写入日志或检查点。不要在仅分析已有报告的请求中启动采集。[Nsight Systems 采集语义](https://docs.nvidia.com/nsight-systems/UserGuide/index.html)

## 3. PyTorch 算子关联

`examples/operator_workload.py` 使用 `torch.autograd.profiler.emit_nvtx(record_shapes=True)`，执行三轮 eager 矩阵乘法、ReLU、归约和反向传播。先记录算子范围，再用官方 `nvtx_kern_sum` 查询启动关联。[PyTorch NVTX 说明](https://docs.pytorch.org/docs/main/autograd.html#torch.autograd.profiler.emit_nvtx)

```json
{"report_id":"采集返回的ID","query":{"name_contains":"aten::mm","limit":20}}
```

以上参数传给 `nsight_operator_summary`。默认筛选 `aten::`，返回原始 NVTX 标签、kernel 名称、关联次数及 GPU 累计耗时。它是范围/kernel 分组表；嵌套算子可能重复关联同一个 kernel，不能把全部行相加作为唯一算子 GPU 总耗时。名称筛选沿用官方报告的名称列匹配规则。

旧报告没有算子标注时，模型不能从 cudnn/cutlass 名称可靠恢复 aten 身份。本版不支持 `torch.compile`、融合图的完整自动归因，也不自动改写用户训练代码。

## 4. 可选 Nsight Compute 报告

安装 Compute，确保 `ncu` 在 PATH 中，或设置 `NSIGHT_NCU_PATH` 后执行 setup。Windows 可自动发现常见 NVIDIA 安装路径。缺少 Compute 不影响 Systems；导入已有 `.ncu-rep` 不要求当前机器具有对应 GPU。

对 Codex 说：

> 打开 /absolute/report.ncu-rep，查询这个 kernel 的 occupancy、SM/DRAM 吞吐和 warp stall。列出缺失的指标，保留单位，把证据导出成 JSON。

工具顺序：`nsight_compute_doctor` → `nsight_compute_open_report` → `nsight_compute_metrics`。可用组固定为：

| group | 内容 |
| --- | --- |
| `occupancy` | 实测活跃 warp 占比及 blocks/registers/shared memory/warps 的限制 |
| `throughput` | SM、DRAM、L1/L2 等资源相对峰值吞吐 |
| `memory` | DRAM 字节数、带宽及缓存命中率 |
| `stalls` | 十类固定 warp stall 原因的 ratio/percentage 变体 |
| `launch` | kernel 时长、寄存器、shared memory、block/grid 大小 |

```json
{"report_id":"ncu-报告ID","group":"occupancy","query":{"name_contains":"gemm","kernel_id":"0","offset":0,"limit":20}}
```

kernel 名称筛选和 `kernel_id` 可单独使用。分页对象是 **kernel/metric 行**，不是 kernel 数量。每行保留精确指标名、单位、数字和 `Raw Value`；`missing_metrics` 表示报告未包含某个请求指标，`measurement_status="unavailable"` 的值为 null。空名称匹配与没有采集整个指标组是不同情况。

Compute 导入使用官方 raw CSV、关闭用户 config，不开放任意指标/section/规则脚本。`result_id` 可直接交给现有 `nsight_export_analysis`。Compute 和 Systems 的报告 ID、kernel ID、时间轴不能自动混用。

本版只读 Compute 报告，**不提供 ncu 自动采集**。需要额外数据时，应在目标 GPU 上另行采集适当 section，并检查 GPU 计数器权限；本机安装 ncu 不会给旧 `.nsys-rep` 添加硬件计数器。Compute 可能通过重放收集指标，时长也可能受干预；高 occupancy 不等于更快，stall ratio 与 percentage 的分母不同。[Compute 官方说明](https://docs.nvidia.com/nsight-compute/ProfilingGuide/index.html)

## 5. 验证与边界

真实平台、版本、测试结果和复核方式见 [v1.1 验证记录](VALIDATION-v1.1.md)。Linux 的验证环境会明确标注容器/WSL，不扩大为所有 Linux 发行版或所有 GPU 的认证。Windows 的 PyTorch eager 标注验证也不代表 Linux 任意模型归因认证。

新增功能以这条有限流程收敛：本地受控 Systems 采集 → 热点定位 → 已记录的 NVTX 算子关联 → 可选 Compute 报告深入查询 → 导出。远程管理、Compute 自动采集、编译/融合图归因和自动优化实验继续排除。
