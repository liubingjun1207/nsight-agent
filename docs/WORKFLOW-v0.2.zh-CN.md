# v0.2：发现训练范围、比较性能、导出证据

首次使用先完成 [安装与接入](GETTING_STARTED.zh-CN.md)。v0.1 的六个工具保持兼容，新版增加四个工具，共十个。每次分析还会返回 `result_id`、记录时间和来源信息。

## 1. 发现 NVTX 范围

向 Codex 发送：

> 打开项目里的 examples/reports/baseline_nvtx.nsys-rep，发现 NVTX 范围，然后显示 Train 的单次范围明细。

`nsight_nvtx_summary` 返回 Push/Pop 与 Start/End 的名称、类型、次数和耗时，默认按累计耗时降序。`nsight_nvtx_trace` 返回 Push/Pop 明细，默认按开始时间升序；包含起止时间、PID、TID、层级、父范围和 `time_query`。

> 使用刚才范围的 time_query，查询其中最耗时的十个 kernel，以及同步 API 的 CPU 耗时。

`time_query` 可以直接作为现有分析工具的 `query`。缺少有效起止时间时该字段为空。时间窗口会包含完整的重叠事件，也可能包含其他线程或设备的并发工作；它不是 kernel 启动归因。

官方名称可能是 `:Train`，包含域名前缀。工具保留原值，不自动拼成 `--filter-nvtx` 表达式。`RangeId` 也不是筛选序号。使用返回的时间窗口最直接；已知有效范围时仍可使用 `nvtx="Train"`。Start/End 仅提供汇总，暂不提供单次实例发现。

CPU 标记区间不代表 GPU 已经完成；嵌套 NVTX 耗时也不能相加作为应用总耗时。

## 2. 对比优化前后

> 再打开 examples/reports/firstOptimization.nsys-rep，作为 candidate。先前的报告作为 baseline。两边分别限定到 Train，比较 kernel、CUDA API、内存耗时和内存字节数。显示次数变化、新增和消失项，不要把累计耗时变化直接解释成整体加速。

两份样例均来自 NVIDIA 的同一公开教程，保留原始许可；它们不是本项目在受控环境中重新跑出的基准。

开发者可调用 `nsight_compare`：

```json
{
  "baseline_report_id":"BASELINE_ID",
  "candidate_report_id":"CANDIDATE_ID",
  "kind":"kernel_summary",
  "baseline_scope":{"nvtx":"Train"},
  "candidate_scope":{"nvtx":"Train"},
  "query":{"limit":10}
}
```

| 参数 | 含义 |
| --- | --- |
| `kind` | `kernel_summary`（默认）、`cuda_api_summary`、`memory_time`、`memory_size` |
| 两侧 `scope` | 各自填写 `start_ns/end_ns` 或 `nvtx`；省略则分析整份报告 |
| `query.name_contains` | 对两侧共同应用、不区分大小写的名称包含筛选 |
| `query.sort_by` | `delta_total`（默认）、`absolute_delta_total`、`baseline_total`、`candidate_total`、`name` |
| `query.descending` | 默认 true |
| `query.offset/limit` | 默认 0/20，每页最多 200 行 |

对比先读取完整官方统计，再按完整名称精确匹配，最后分页。名称大小写不同、重命名、融合或拆分不会被自动配对；重复名称会明确报错。排序值相同按名称稳定排列，缺失排序值始终放在最后。

每行包含两侧原值、`matched/added/removed` 状态、各数值列的差异及 `count_changed`。`status_counts` 和 `count_changed_rows` 描述名称筛选后的完整匹配结果，不仅当前页。

- 差值为 candidate − baseline；相对变化为差值 / baseline × 100。
- baseline 为零时，相对变化为空，原因是 `zero_baseline`。
- 某侧缺失时保留空值，差异原因是 `missing_side`，不假装测得零。默认新增/消失项在末尾；可按 candidate/baseline 累计值排序查看。
- 次数变化可能导致累计耗时变化，应同时看单次平均耗时。中位数等值直接来自官方统计，不重新聚合。
- 两侧 `Time (%)` 各用自己的分母，绝对差以“百分点”解释。
- 工具不保证工作量相等，也不会给出应用整体加速比或自动根因结论。

## 3. 导出可复核记录

> 把刚才的范围发现和四类对比结果分别导出为 Markdown 和 JSON，保留来源、单位、筛选条件及分页信息。

调用 `nsight_export_analysis`，填写分析返回的结果 ID：

```json
{"result_ids":["NVTX_RESULT_ID","KERNEL_COMPARE_ID","API_COMPARE_ID"],"format":"markdown"}
```

`format` 也可填 `json`。每次导出都在缓存目录的 `exports` 下创建唯一文件，返回绝对路径，不重新运行 Nsight。Markdown 含可读表格及完整 JSON 证据，便于与 JSON 导出核对。

只导出选中的结果页面；查看 `total_rows/offset/next_offset` 判断是否完整，需要更多行时先查询下一页。服务保留当前会话最近 100 次分析快照，重启或超出保留数后需要重新分析。导出文件不会随服务重启消失，可按需手动清理。

文件包含本地路径和命令，分享前检查路径信息。复核命令引用的缓存 SQLite 需要仍然存在；原报告路径及筛选条件也会保留。导出保存统计证据，模型的分析解释仍在对话中。

## 4. 升级和故障处理

在原虚拟环境安装 v0.2.0 wheel，或更新源码后重新安装，再重新连接 MCP、打开报告。Python 路径不变时无需修改 Codex 配置；自行复制过分析 skill 的用户可更新该文件夹。

缺少 NVTX 官方报告时，新增工具会返回能力错误，原有工具仍可使用；查看 `nsight_doctor.optional_reports`。对比涉及两侧导出和统计，耗时可能长于单报告；大报告应让 Codex 工具超时覆盖整个操作。

过期结果 ID 需重新查询；缺失数据不是零；没有匹配结果时放宽筛选并核对范围。更多问题见 [入门指南](GETTING_STARTED.zh-CN.md)。真实示例见 [演示](DEMO.md)，环境与验证范围见 [验证记录](VALIDATION.md)。
