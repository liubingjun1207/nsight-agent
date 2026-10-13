"""A real stdio handshake, tool discovery and tool error path, without Nsight/GPU."""

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_contract():
    async def check():
        params = StdioServerParameters(command=sys.executable, args=["-m", "nsight_agent"])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                assert all(t.outputSchema is not None for t in result.tools)
                assert {t.name for t in result.tools} == {
                    "nsight_analysis_rules",
                    "nsight_analyze",
                    "nsight_doctor",
                    "nsight_open_report",
                    "nsight_capabilities",
                    "nsight_stats",
                    "nsight_kernel_summary",
                    "nsight_kernel_trace",
                    "nsight_cuda_api_summary",
                    "nsight_memory_summary",
                    "nsight_nvtx_summary",
                    "nsight_nvtx_trace",
                    "nsight_compare",
                    "nsight_export_analysis",
                    "nsight_capture_targets",
                    "nsight_capture",
                    "nsight_operator_summary",
                    "nsight_compute_doctor",
                    "nsight_compute_open_report",
                    "nsight_compute_metrics",
                }
                error = await session.call_tool(
                    "nsight_open_report", {"path": "does-not-exist.nsys-rep"}
                )
                assert error.isError

    asyncio.run(check())


def test_stdio_cache_error_is_actionable(tmp_path):
    cache = tmp_path / "cache-file"
    cache.write_bytes(b"not a directory")

    async def check():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "nsight_agent"],
            env={"NSIGHT_CACHE_DIR": str(cache)},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                error = await session.call_tool("nsight_doctor", {})
                assert error.isError
                message = "\n".join(item.text for item in error.content if item.type == "text")
                assert "CACHE_IO_ERROR" in message and "NSIGHT_CACHE_DIR" in message
                assert "Recovery:" in message and "Traceback" not in message

    asyncio.run(check())
