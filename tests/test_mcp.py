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
                }
                error = await session.call_tool(
                    "nsight_open_report", {"path": "does-not-exist.nsys-rep"}
                )
                assert error.isError

    asyncio.run(check())
