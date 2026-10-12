# Nsight Agent v0.2 中文入门指南

这份指南适用于在 Windows 上，通过 Codex 分析现成的 Nsight Systems 报告。完成后，你可以直接问：“列出最耗时的十个 CUDA kernel”，由 Codex 调用工具得到可复核的统计。

## 1. 准备环境

| 需要什么 | 如何准备 | 如何检查 |
| --- | --- | --- |
| Python 3.11 或以上 | 从 [Python Windows 官网](https://www.python.org/downloads/windows/) 安装；安装时启用加入 PATH | PowerShell 执行 `python --version` |
| NVIDIA Nsight Systems | 从 [Nsight Systems 官方页面](https://developer.nvidia.com/nsight-systems) 安装 Windows 版本；本项目验证版本为 2025.6.3 | 安装后由本项目的 `--doctor` 自动检查 |
| Codex 本地客户端 | 按 [Codex 官方说明](https://developers.openai.com/codex/quickstart) 安装并登录；桌面客户端用于对话 | 确认能正常对话；若使用命令行管理 MCP，执行 `codex --version` |
| 报告或公开样例 | `.nsys-rep` 或 Nsight 导出的 `.sqlite` | 本项目源代码包已包含公开样例 |

分析已有报告不要求 Windows 本机有 NVIDIA GPU，也不要求安装 PyTorch。只有自行采集示例工作负载才需要 CUDA GPU 与 PyTorch。项目验证的是 Windows 阅读 Linux 报告；并不代表所有采集版本都兼容。

## 2. 安装 v0.2

解压发布的源代码包 `nsight_agent-0.2.0.tar.gz`，或 GitHub 的源代码 ZIP。进入包含 `pyproject.toml` 的目录，在资源管理器地址栏输入 `powershell` 打开终端。

执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m nsight_agent --doctor
```

无需激活虚拟环境；这里始终明确使用项目的 `.venv` Python。

成功的检查结果应包含：

```json
{
  "version": "NVIDIA Nsight Systems version ...",
  "nsys_path": "...nsys.exe",
  "missing_reports": []
}
```

如果 Nsight 未被自动发现，指定本机实际安装路径，再执行检查：

```powershell
$env:NSIGHT_NSYS_PATH = 'C:\Program Files\NVIDIA Corporation\Nsight Systems 2025.6.3\target-windows-x64\nsys.exe'
.\.venv\Scripts\python.exe -m nsight_agent --doctor
```

上面的版本目录是示例，必须换成你的安装目录。该环境变量只作用于当前 PowerShell；下一步接入命令会把实际路径存进 Codex 的 Nsight 服务配置。

若只想安装 wheel，也可以在同一个虚拟环境执行：

```powershell
.\.venv\Scripts\python.exe -m pip install 'C:\你的下载目录\nsight_agent-0.2.0-py3-none-any.whl'
```

wheel 不包含公开报告和指南；第一次使用建议下载完整源代码包。

## 3. 接入 Codex

在同一目录执行：

```powershell
.\.venv\Scripts\python.exe -m nsight_agent --configure-codex
```

该命令会：

1. 确认当前 Python 与 Nsight 路径。
2. 找到 `~/.codex/config.toml`（设置了 `CODEX_HOME` 时使用该目录）。
3. 在同目录创建带时间戳的配置备份。
4. 只更新 `nsight` 服务，启用本地 STDIO，并设置启动超时 30 秒、工具超时 300 秒、单个 Nsight 命令超时 120 秒。

成功时输出 `"status": "configured"`。随后在 Codex 的 MCP 设置中重新连接/重启服务；如果当前聊天仍看不到新工具，重启桌面客户端并在新会话中验证。[官方 MCP 配置说明](https://developers.openai.com/codex/mcp)

手动配置方式见 [README 配置片段](../README.md#install-and-connect)。不建议只执行 `codex mcp add` 而漏设工具超时；两种方式都应设置 `tool_timeout_sec = 300`。

## 4. 验证工具真正可用

先检查“配置已经注册”，有 Codex CLI 的用户可以执行：

```powershell
codex mcp get nsight
```

应看到 `enabled: true`、正确的 `.venv\Scripts\python.exe` 路径以及 300 秒工具超时。这只能确认配置，不能代替真实连接检查。

再在 Codex 中发送：

> 使用 nsight_doctor 检查本机 Nsight，列出你当前能调用的十个 nsight 工具。

应看到这十个工具：`nsight_doctor`、`nsight_open_report`、`nsight_kernel_summary`、`nsight_kernel_trace`、`nsight_cuda_api_summary`、`nsight_memory_summary`、`nsight_nvtx_summary`、`nsight_nvtx_trace`、`nsight_compare`、`nsight_export_analysis`。若工具不存在，请参照第 8 节，而不是让模型用自行生成的 SQL 替代。

## 5. 跑通第一次分析

在项目终端获取公开报告的绝对路径：

```powershell
(Resolve-Path '.\examples\reports\baseline_nvtx.nsys-rep').Path
```

把输出的路径填入下面的提问，发给 Codex：

> 使用 nsight 工具打开“报告的绝对路径”，按累计 GPU 执行时间降序列出前十个 CUDA kernel。显示名称、累计耗时（ms）、执行次数、平均耗时（μs）与占比，并说明占比的分母。

公开样例的预期结果：50 类 kernel；第一名名称包含 `wgrad_alg0_engine`，执行 938 次，累计 1,266,481,454 ns（约 1,266.481 ms），占比 24.9%。这是一份固定的 Linux/Tesla T4 报告，其数字不依赖你的本机 GPU 性能。[样例来源与许可](../examples/reports/README.md)

再发送：

> 查看刚才第一名 kernel 的执行明细，按开始时间升序返回五条，包含设备、stream 和单次耗时。

然后：

> 按 Train NVTX 范围重新统计，列出最耗时的五个 kernel，比较第一名的累计耗时与占比。

该范围内第一名累计耗时仍为 1,266,481,454 ns，占比为 25.6%，原因是统计范围改变了分母。更多预期输出见 [完整演示](DEMO.md)。

## 6. 十个工具怎么问

| 工具 | 可直接复制的提问 |
| --- | --- |
| `nsight_doctor` | “检查 Nsight 安装版本与分析命令是否可用。” |
| `nsight_open_report` | “打开这个本地报告：报告绝对路径，后续分析都使用它。” |
| `nsight_kernel_summary` | “列出名字包含 gemm 的 kernel，按累计耗时降序显示十条。” |
| `nsight_kernel_trace` | “查看这个 kernel 的每次执行，按开始时间升序显示二十条。” |
| `nsight_cuda_api_summary` | “列出名称包含 Synchronize 的 CUDA API，显示 CPU 侧调用耗时与次数。” |
| `nsight_memory_summary` | “分别查询内存操作耗时和字节数；区分 memcpy 方向与 memset。” |

限定区间的提问：

> 只分析报告时间轴 0 到 10 秒的 kernel，显示前十名。

> 只分析 Train NVTX 范围，并列出其 CUDA API 耗时。

分页提问：

> 继续查看下一页二十条，沿用当前筛选和排序。

日常使用时由 Codex 生成参数；不用手写 JSON。开发者需要直接调用时，参数放在 `query` 对象内：

```json
{"report_id":"打开报告后返回的ID","query":{"start_ns":0,"end_ns":10000000000,"limit":10}}
```

NVTX 参数格式为 `范围名[@域名][/序号]`，序号从 0 开始；时间区间与 NVTX 不能同时指定。报告 ID 仅在当前服务会话有效，重启后重新打开报告。v0.2 可用 `nsight_nvtx_summary` 发现范围，再用 `nsight_nvtx_trace` 查看 Push/Pop 实例；可直接使用返回的 `time_query`，不要把 `RangeId` 当作筛选序号。

新增四个工具的提问：

- “发现这份报告的 NVTX 范围，查看 Train 的单次范围明细。”
- “打开优化后的报告，分别选择两份报告的 Train 范围，比较 kernel、API 和内存统计，说明次数是否变化。”
- “把刚才的分析结果分别导出为 Markdown 和 JSON，标明这是哪些分页结果。”

参数、真实样例和完整操作见 [v0.2 流程指南](WORKFLOW-v0.2.zh-CN.md)。

## 7. 正确阅读数字

- 累计耗时是同一 kernel 多次执行的耗时之和；并发 kernel 会重叠，因此累计值可能超过实际经过的时间。
- `Time (%)` 的分母是 Nsight 官方报告中所有相应事件的累计耗时。名称筛选和分页不重新计算分母。
- CPU 侧 CUDA API 时间与 GPU kernel 执行时间是不同指标。
- 时间/NVTX 筛选包含与范围重叠的完整事件，耗时不会裁剪到边界。
- “没有匹配数据”不证明实际 GPU 没有活动；报告可能未采集所需事件。
- CUDA kernel 与 PyTorch 算子不是一一对应，v0.2 不承诺框架算子归因、GPU 利用率诊断或瓶颈根因判定。

## 8. 常见故障

| 现象 | 检查与处理 |
| --- | --- |
| `python` 找不到或打开商店 | 完成 Python 安装和 PATH 配置，重新打开 PowerShell；必要时使用 Python 安装目录的绝对路径 |
| `No module named nsight_agent` | 使用安装时的 `.venv\Scripts\python.exe`；在该环境重新执行安装命令和 `--configure-codex` |
| `Nsight Systems CLI not found` | 指定 `NSIGHT_NSYS_PATH`；确认指向 Systems 的 `nsys.exe`，不是 Nsight Compute 的 `ncu.exe` |
| `missing_reports` 非空或选项不支持 | 检查 Nsight 版本；升级到已支持所需官方报告的版本，再运行 doctor |
| Codex 中没有工具 | 检查 MCP 服务启用状态、Python 路径与配置位置；重新连接或重启客户端 |
| 工具启动失败 | 在终端运行相同 Python 的 `--doctor`；不要用别的 Python 检查后就认为配置正确 |
| 报告路径无效 | 用 `Resolve-Path` 获取绝对路径；确认文件在当前 Windows 机器上，不是仅存在于 Linux 服务器 |
| 报告读取失败或版本不兼容 | 先用本机 Nsight 打开同一报告；较新的采集报告可能需要更新的 Windows reader |
| 提示缺少 CUDA/NVTX 数据 | 确认采集时启用了 `--trace=cuda,nvtx`，或改用具有所需数据的报告 |
| 结果为空 | 放宽名称、时间或 NVTX 筛选；核对范围名、域名、序号与时间单位 |
| `Unknown or expired result_id` | 会话只保留最近 100 次分析；重新运行所需分析后导出 |
| `Unknown report_id` | MCP 重启后重新打开报告；不要复用旧会话 ID |
| `Unknown sort column` | 使用返回结果里的完整列名，例如 `Duration (ns)` 或 `Start (ns)` |
| 超时 | 检查 300 秒工具超时是否生效；收窄查询范围。首次导出与复制仍需处理报告，可根据报告规模提高 `NSIGHT_TIMEOUT_SECONDS`，并将 Codex 超时设得更长 |
| 磁盘空间不足 | 改用容量充足的 `NSIGHT_CACHE_DIR`；停止服务后清理旧会话缓存 |

错误信息、Nsight 版本、工具名和去除敏感内容后的复现步骤可以用于提交问题；不需要上传自己的完整业务报告。

## 9. 更新、卸载与缓存

更新源代码版本后，在原虚拟环境重新安装并接入：

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m nsight_agent --configure-codex
```

如果最初装的是 wheel，改为安装新 wheel 文件。随后重新连接服务，运行 doctor 并重新打开报告。移动项目目录后也需重新接入，否则 Codex 仍会启动旧路径。

卸载接入和 Python 包：

```powershell
codex mcp remove nsight
.\.venv\Scripts\python.exe -m pip uninstall nsight-agent
```

没有 CLI 时可在 Codex MCP 设置中移除 `nsight`。不要删除其他服务配置。指南的安装与接入不自动安装可选 skill；若自行复制了 `nsight-analysis`，可单独移除该 skill 文件夹。

doctor 的 `cache_dir` 显示实际缓存路径。默认在 Windows 本地应用数据目录的 `nsight-agent` 下；每个 `session-*` 文件夹是一次服务会话生成的副本和导出。**停止服务后**可以删除旧 `session-*` 目录，原始报告不在其中。配置备份位于 Codex 配置同目录，文件名为 `config.toml.before-nsight-*.bak`；恢复前先检查，避免覆盖后来新增的其他配置。

## 10. 自行采集与后续阅读

自己的 Linux GPU 环境可使用 [示例采集说明](../examples/README.md) 生成报告，传回 Windows 后按相同步骤打开。服务不会自行登录服务器或启动你的训练任务。

- [完整接口与参数](../README.md#tools)
- [逐步演示及统计预期](DEMO.md)
- [版本验证记录](VALIDATION.md)
- [项目许可](../LICENSE)
