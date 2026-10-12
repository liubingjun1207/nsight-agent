# 最终验收：能力、模型流程和安装发布

本项目的完成标准见 [最终范围](PROJECT_SCOPE.zh-CN.md)。以下三层分别留证，任何一层未通过都不能宣布 v1.0 验收完成。

## 1. 能力与数值正确性

- 18 个 CUDA/NVTX 报告的白名单、能力检测、字段与排序正确。
- 真实 Linux 报告在 Windows 上的输出与直接运行 Nsight 相符；报告缺少事件时明确失败或说明空表语义。
- 检查报告不被修改，名称/时间/NVTX 过滤、分页、对比和导出保持一致。
- 覆盖失效 ID、无匹配、版本/参数不兼容、错误路径、命令失败和超时。

运行 `NSIGHT_INTEGRATION=1` 的测试套件。公开 Linux 样例缺少 Start/End 事件，因此该缺失路径也必须验证；额外的本地 Windows Start/End 小样例可通过 `NSIGHT_STARTEND_REPORT` 验证非空结果，不能称其为 Linux 采集报告。

## 2. 模型实际使用

已登录 Codex CLI 的本机环境可以运行：

```powershell
.\.venv\Scripts\python.exe examples/evaluate_codex.py --reports-dir examples/reports --output-dir .cache/model-evaluation
```

该验证只配置 nsight MCP，保留当前用户选择的模型，使用临时会话、只读 shell 策略和官方 JSONL 事件。Nsight 服务可生成受控缓存与导出文件。此验证会使用已登录账号的模型额度，默认不在公开 CI 中执行，也不复制登录凭据。

固定四组问题：

| 用例 | 核对内容 |
| --- | --- |
| core | Top kernel、执行明细、范围发现、十秒边界、grid/block、API 汇总/明细、内存时间/字节/明细 |
| launch | 发射/排队/执行、NVTX GPU 投影、launch-based 范围归属、CPU/GPU 分类 |
| compare | 两侧各自的 Train 范围、四类对比、实际 Markdown/JSON 文件 |
| diagnostics | 无效报告、Start/End 缺少数据、无匹配名称及范围外的 Nsight Compute 问题 |

使用 `--case core --repetitions 2` 复查代表性流程。脚本要求观察到实际 MCP 调用和相应结果，核对关键数值及独立范围；若使用 shell、网页或其他 MCP 代替分析，就判为失败。不能只根据模型回答“成功”就通过。

人工检查最终回答的单位、分母、CPU/GPU 区别、投影/排队含义与缺失数据解释。记录客户端、模型、重复次数及通过率；不宣称所有自然语言表达均可成功。

原始 JSONL、stderr 和回答留在本地 `.cache`，不得提交登录文件。可公开汇总用例、实际工具/报告列表和统计，不上传业务报告或私人环境日志。

## 3. 从安装到使用

- 在新目录解压源码包，执行安装脚本；或在新虚拟环境安装发布 wheel。
- `--setup` 完成真实 STDIO 验证、带备份的配置写入和打包 skill 安装；用户自定义 skill 被保留并提示。
- `--check-connection` 使用实际注册的 Python/参数/环境运行握手和工具调用；可加 `--report` 验证真实样例。它也检查禁用或隐藏工具的配置。
- 重新连接 Codex 后，按文档打开公开样例并完成一组真实提问。
- 核对完整源码包、wheel、安装脚本、文档及校验文件；Windows/Linux CI 检查源码与已安装 wheel。
- 更新和卸载说明不能遗漏 required MCP 的含义：若 Python 路径失效，Codex 会明确启动失败；修复路径或移除 nsight 配置后再启动。

配置写入、SDK 握手、真实模型分析是三个独立结论。发布记录必须说明各自验证结果。
