# Validation record — v1.0.0

Date: 2026-10-12 (Asia/Shanghai). Windows, Python 3.13.5, Nsight Systems `2025.6.3.343-256337165561v0`. Development uses MCP SDK 1.27.0; the isolated installed-wheel environment uses SDK 1.30.0 and Pydantic 2.14.1.

## Numeric and transport checks

143 distinct tests pass: 104 GPU-free checks and 39 real integration checks. The real suite compares official CLI output with service/MCP output, checks all 18 report paths (including the public capture's missing Start/End data), report options, original source preservation, scopes, comparisons and exports. Additional evaluator checks reject a failed tool status even when the CLI error field is null.

The development suite completed 139 checks in 506.40 seconds; four evaluator checks were added/verified afterward. The final GPU-free suite has 104 passing tests. A fresh environment importing the installed wheel passed the GPU-free suite available at installation plus the final evaluator checks. The packaged runtime was also used for real SDK connections, sample queries and the model evaluations below.

The public NVIDIA Linux/Tesla T4 artifacts are unchanged. Baseline SHA-256: `760052039bd392c997fdf2533a97292825121dfe818e18f1fd6b127e79ffedea`; candidate SHA-256: `d81a008bdccd386cd1a382b49f87e90ff5bbd729bd036a9bbe11d24fa1c06980`. [Provenance and retained license](../examples/reports/README.md).

The public baseline lacks Start/End events and returns `MISSING_DATA`. A separate locally generated Windows/RTX 4060/PyTorch capture verifies three `AsyncStep` Start/End instances against the direct CLI. It stays in ignored cache and is not represented as a Linux capture; the [minimal workload](../examples/startend_workload.py) makes this positive check reproducible.

## Real Codex model use

Configured model: `gpt-6.1-sol`; client: `codex-cli 0.162.0-alpha.17.2`. Five clean runs using the installed wheel passed, with **50 actual MCP calls**. The core flow was repeated twice. JSONL events verify tool usage, report selection, the ten-second boundary, top kernel numeric evidence, both Train scopes, real export files and diagnostic codes. Final answers were reviewed for units, denominators, CPU/GPU distinctions, null queue times, NVTX projection/association limitations and missing-data interpretation.

| Scenario | Runs passed | Actual calls |
| --- | ---: | ---: |
| Core query/discovery/API/memory workflow | 2 / 2 | 13 + 13 |
| Launch, queue, GPU projection and NVTX/kernel association | 1 / 1 | 8 |
| Independent Train comparisons and Markdown/JSON export | 1 / 1 | 11 |
| Invalid path, missing Start/End data, no match and out-of-scope Compute | 1 / 1 | 5 |

Normal runs had no failed calls; diagnostic runs intentionally exercised `INVALID_REPORT` and `MISSING_DATA`. No shell/SQL/web or other MCP was used as an analysis fallback. [Public machine-readable summary](evaluation-results.json) contains aggregate evidence, not raw private paths, account authentication or conversation logs.

These are five fixed Chinese scenarios, not a statistical guarantee for all prompts or clients. The evaluator uses isolated ephemeral Codex sessions with only the trusted nsight server, required startup and explicit tool approval for unattended evaluation. Normal interactive approval behavior depends on the user's client settings. Source-pilot findings were used to remove unrelated diagnostic paths from normal prompts and tighten failed-call detection; the published counts cover the clean final scenarios only.

## Installation and distribution checks

- A fresh isolated environment installed the wheel; imports resolved to its site-packages, and the packaged skill was found and installed correctly.
- An independent directory extracted the source archive and ran `install.ps1` from scratch. Environment creation, installation, preflight handshake, 12-tool/18-report discovery, configuration and skill installation all passed.
- `--check-connection --report` used the actual registered environment and returned the expected top kernel: 1,266,481,454 ns, 938 instances, among 50 names.
- The same wheel upgraded the local Codex environment. Unrelated configuration was preserved with a backup; required startup, 600s tool timeout and the analysis skill were configured.
- CI checks source and installed-wheel GPU-free behavior on Windows/Linux, Python 3.11/3.13. [Live CI results](https://github.com/liubingjun1207/nsight-agent/actions) are separate from the real Windows reader and model gates.

## Reproduce and limits

See [acceptance procedure](ACCEPTANCE.zh-CN.md), [report catalog](REPORTS.md), [installation guide](GETTING_STARTED.zh-CN.md), and [fixed scope](PROJECT_SCOPE.zh-CN.md). Enable `NSIGHT_INTEGRATION=1` for real reader tests; optionally point `NSIGHT_STARTEND_REPORT` at the documented extra capture. Real model evaluation reuses local Codex login and remains opt-in, outside public CI.

One reader version, two public Linux captures and one local Windows positive Start/End capture are checked. No certification of every collector/model/platform, multi-GPU scenario, GUI, Nsight Compute or framework attribution is claimed. v1.0 closes feature development once its release gates pass; further work is maintenance within the fixed scope.
