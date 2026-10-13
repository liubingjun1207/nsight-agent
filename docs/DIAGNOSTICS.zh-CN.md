# 官方瓶颈诊断（v1.2.0）

本次有限扩展接入六条 Nsight Systems 官方诊断规则，帮助 Codex 找到“为什么可能慢”的证据。它不自动证明根因、改写训练代码或增加任意脚本执行接口。原有十八个工具和十八个统计报告继续兼容，新增两个工具后合计二十个。

## 安装与连接

从 [v1.2.0 Release](https://github.com/liubingjun1207/nsight-agent/releases/tag/v1.2.0) 下载完整源码包，解压后在包含 `pyproject.toml` 的目录安装。v1.1.0 包没有这两个诊断工具：

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m nsight_agent --setup
.\.venv\Scripts\python.exe -m nsight_agent --check-connection
```

首次安装没有 `.venv` 时，先执行 `python -m venv .venv`。Linux 使用 `.venv/bin/python`。setup 会备份并更新 nsight 配置，安装打包的分析 skill；自定义 skill 修改会被保留。重新连接 Codex MCP 后，确认有 `nsight_analysis_rules` 和 `nsight_analyze`，先运行规则发现检查本机版本是否支持。不需要为现成报告准备 GPU，也不需要额外模型 API key。

手动配置的 `env_vars` 会从执行连接检查的本地进程读取指定环境变量；`env` 的明确值覆盖同名转发值，`cwd` 会传入实际 STDIO 子进程。未设置的转发变量会略过，不会继承未列出的额外变量。默认系统环境由 MCP SDK 提供。本地检查不支持远程 executor 或 remote 来源变量，会明确报错；它无法读取另一个已运行 Codex 进程自己的环境。

## 两个工具与六条规则

`nsight_analysis_rules()` 返回本机版本、六条规则的可用状态、所需参数、默认值和统计含义。发现其他官方规则不会扩大白名单。

`nsight_analyze(report_id, rule, query?, options?)` 接受通过 `nsight_open_report` 注册的 Systems 报告 ID，运行一条规则。Compute 报告 ID 不适用。

| rule | 检查内容 | 耗时含义 / 特别参数 |
| --- | --- | --- |
| `cuda_api_sync` | CUDA device/stream 同步调用 | CPU API 耗时；并非所有可能阻塞的 CUDA API |
| `cuda_memcpy_async` | 使用可页内存的异步 CUDA 拷贝 | GPU 拷贝耗时，不是 CPU 阻塞时间 |
| `cuda_memcpy_sync` | 官方规则选择的同步拷贝 | GPU 拷贝耗时；规则排除部分小型 H2D 和同设备拷贝 |
| `cuda_memset_sync` | 官方规则选择的同步 memset | GPU memset 耗时，针对 pinned/Unified Memory 等选定模式 |
| `gpu_gaps` | 每个进程/设备的 GPU 空隙 | `options.gap_ms`，整数 0–60000，默认 500 ms；返回超过阈值的空隙 |
| `gpu_time_util` | 低 GPU 时间利用率区间 | `threshold_percent` 0–100，默认 50%；`chunks` 1–1000，默认 30 |

`gap_ms` 仅适用于 `gpu_gaps`；`threshold_percent` 和 `chunks` 仅适用于 `gpu_time_util`。不匹配的参数会报错。这里没有按设备筛选的接口；GPU 规则在输出中保留 PID、Device ID、Context ID。

## 自然语言流程

可以直接对 Codex 说：

> 打开 examples/reports/baseline_nvtx.nsys-rep，发现官方诊断规则。检查同步调用、可页内存异步拷贝和 GPU 空隙，空隙阈值设为 1 ms，每项最多五行。沿最长空隙的时间区间查看 CPU CUDA API 明细，区分诊断候选和已确认根因。

训练 step 的问题应先找到实际范围：

> 发现报告里的 NVTX 范围，选择 Train 的一次范围。检查该范围的低 GPU 时间利用率，说明阈值和统计范围；查看其中的同步调用。不要把时间利用率解释为 SM 利用率。

也可以指定明确时间：

> 检查报告前一秒的同步调用，列出最长的三个，并导出这些诊断结果的 JSON 证据。

推荐流程是：发现能力 → 打开报告 → 发现范围 → 选择相关规则 → 沿返回的 `time_query` 查询 API/GPU/NVTX 明细 → 解释支持与不支持的结论 → 导出选定证据。无需每次都运行所有规则。

## 工具参数示例

GPU 空隙：

```json
{"report_id":"ID_FROM_OPEN","rule":"gpu_gaps","query":{"limit":5},"options":{"gap_ms":1}}
```

已知 NVTX 范围内的时间利用率：

```json
{"report_id":"ID_FROM_OPEN","rule":"gpu_time_util","query":{"nvtx":"Train","limit":5},"options":{"threshold_percent":50,"chunks":30}}
```

前一秒的同步调用：

```json
{"report_id":"ID_FROM_OPEN","rule":"cuda_api_sync","query":{"start_ns":0,"end_ns":1000000000,"name_contains":"StreamSynchronize","limit":5}}
```

时间、NVTX、API 名称、排序、分页都放在 `query`。时间使用报告相对纳秒；时间和 NVTX 不能同时指定。NVTX 使用既有 `name[@domain][/index]` 语法。`name_contains` 仅适用于带 API Name 的四条 CUDA 规则。`sort_by` 必须是该规则允许的官方列名，默认按 Duration (ns) 降序。

## 结果如何解释

- `status=findings`：筛选后存在诊断命中。翻到超过末尾的页时仍可能没有行，查看 `total_rows`。
- `status=no_findings`：当前阈值和筛选条件下没有命中，不表示活动为零或程序已经最优。
- `official_findings`：时间/NVTX 筛选后的完整官方命中数量，尚未进行 API 名称筛选；`total_rows` 是名称筛选后的数量。
- `offset`、`next_offset`：每页最多 200 行，可继续查询。服务固定使用 `rows=-1`，关闭 Nsight 默认的 50 行截断后再分页；分页不会降低 Nsight 计算成本。
- `MISSING_DATA`：缺少规则需要的事件或范围数据，与未命中不同；`CAPABILITY_UNAVAILABLE` 表示本机规则/选项/参数不支持；其他失败包含超时、缓存、命令或 schema 错误。
- 每份结果有官方规则名、Nsight 版本、实际参数、筛选、单位、原命令和 `result_id`，可交给 `nsight_export_analysis`。导出保存选定结果页，而非整份报告。

时间过滤沿用官方重叠语义，事件可能跨区间边界。GPU gaps/time utilization 在每个进程/设备的首个至最后一个 GPU 操作之间计算，不覆盖初始/最终闲置。`In-Use (%)` 累加 GPU 操作时间，包含 profiling overhead，并发时可能超过 100%；它不是 SM、Tensor Core、occupancy 或带宽利用率。硬件指标仍需单独的 Compute 报告。

同步/拷贝模式和空隙是候选证据。必须结合范围、时间线和上下文判断它们是否位于关键路径；不能把命中耗时相加直接当作可节省时间。

## 复核与验证

复制结果 `provenance.executable` 和 `provenance.arguments` 的参数数组，在独立目录运行同一官方命令即可复核。服务先把原报告复制并导出到独立缓存，保留原文件。诊断命令有意不加 `--quiet`：2025.6.3 会隐藏缺失数据的 `SKIPPED` 状态。服务仅移除已识别的官方 Processing 行，保留错误判断并解析 CSV。

```powershell
python -m pytest -m 'not integration'
$env:NSIGHT_INTEGRATION = '1'
python -m pytest tests/test_diagnostics_integration.py -q
python examples/evaluate_codex.py --reports-dir examples/reports --output-dir .cache/model-bottlenecks --case bottlenecks
```

最后一项需要本机 Codex 登录和实际模型调用。公开报告中部分规则没有命中，这是正常结果，不代表测试数据缺失。实测平台、结果和未覆盖条件见 [验证记录](VALIDATION-v1.2.md)。
