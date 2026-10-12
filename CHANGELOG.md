# Changelog

## 0.2.0 — 2026-10-12

- Discover NVTX aggregate ranges and individual Push/Pop windows through official Nsight reports.
- Compare complete official kernel, CUDA API, memory-time and memory-size tables across independently selected scopes.
- Preserve exact-name matching, missing/zero-baseline semantics, changed counts and both sides' provenance.
- Export immutable selected analysis pages as Markdown/JSON; retain the latest 100 session results.
- Add a second licensed public NVIDIA Linux capture, a paired workload example, bilingual workflow guides and expanded real CLI/MCP validation.
- Keep the six v0.1 tools compatible; expose optional NVTX capabilities independently.

## 0.1.0 — 2026-10-11

- Six local MCP tools for official Nsight Systems kernel, API and memory statistics.
- Time/NVTX filtering, name matching, sorting and pagination with explicit statistical semantics.
- Windows analysis of a bundled public Linux training capture, including provenance and license.
- Chinese onboarding guide, bilingual README, reusable Codex analysis skill and sample workload.
- `--configure-codex` setup command: configuration backup, isolated nsight settings, 30s startup and 300s tool timeout.
- GPU-free CI, real CLI/MCP integration tests and reproducible demonstration.
