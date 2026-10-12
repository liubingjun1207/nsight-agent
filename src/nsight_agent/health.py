"""Real local STDIO checks; a configured entry alone is not a connection test."""

import asyncio
import os
import sys
import tomllib
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .core import NsightError

TOOLS = {
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


async def probe(command, args, env=None, *, timeout=60, report=None):
    params = StdioServerParameters(command=command, args=args, env=env)
    async with asyncio.timeout(timeout):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = {tool.name for tool in (await session.list_tools()).tools}
                if missing := TOOLS - tools:
                    raise NsightError(
                        f"Installed server is missing tools: {sorted(missing)}",
                        code="TOOLS_MISSING",
                    )
                doctor = await session.call_tool("nsight_doctor", {})
                if doctor.isError:
                    raise NsightError(str(doctor.content), code="NSIGHT_CHECK_FAILED")
                catalog = await session.call_tool("nsight_capabilities", {})
                if catalog.isError or not catalog.structuredContent:
                    raise NsightError("Capability discovery failed.", code="NSIGHT_CHECK_FAILED")
                result = {
                    "status": "connected",
                    "transport": "stdio",
                    "tools": sorted(tools),
                    "available_reports": [
                        r["report"] for r in catalog.structuredContent["reports"] if r["available"]
                    ],
                    "missing_reports": [
                        r["report"]
                        for r in catalog.structuredContent["reports"]
                        if not r["available"]
                    ],
                    "nsight_version": doctor.structuredContent["version"],
                    "note": "Real SDK handshake and tool calls passed. Reconnect Codex to load new tools; this does not test model tool selection.",
                }
                if report:
                    opened = await session.call_tool(
                        "nsight_open_report", {"path": str(Path(report).resolve())}
                    )
                    if opened.isError:
                        raise NsightError(str(opened.content), code="REPORT_CHECK_FAILED")
                    summary = await session.call_tool(
                        "nsight_kernel_summary",
                        {"report_id": opened.structuredContent["report_id"], "query": {"limit": 1}},
                    )
                    if summary.isError:
                        raise NsightError(str(summary.content), code="REPORT_CHECK_FAILED")
                    result["sample"] = {
                        "total_rows": summary.structuredContent["total_rows"],
                        "rows": summary.structuredContent["rows"],
                    }
                return result


def run_probe(command=sys.executable, args=None, env=None, *, timeout=60, report=None):
    try:
        return asyncio.run(
            probe(
                command,
                args if args is not None else ["-m", "nsight_agent"],
                env,
                timeout=timeout,
                report=report,
            )
        )
    except Exception as exc:

        def find_error(error):
            if isinstance(error, NsightError):
                return error
            for child in getattr(error, "exceptions", []):
                if found := find_error(child):
                    return found
            return None

        if found := find_error(exc):
            return found.as_dict()
        if isinstance(exc, NsightError):
            return exc.as_dict()
        return {
            "status": "error",
            "code": "MCP_CONNECTION_FAILED",
            "message": str(exc)[:2000],
            "recovery": "Run --doctor using the configured Python, check paths, reinstall and reconnect Codex.",
        }


def check_connection(*, report=None, config_path=None):
    path = (
        Path(config_path)
        if config_path
        else Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "config.toml"
    )
    try:
        config = tomllib.loads(path.read_text(encoding="utf-8"))
        server = config.get("mcp_servers", {}).get("nsight")
        if not server or not server.get("enabled", True):
            raise NsightError(
                "nsight MCP is absent or disabled in Codex configuration.", code="MCP_NOT_ENABLED"
            )
        allowed = set(server.get("enabled_tools", TOOLS)) - set(server.get("disabled_tools", []))
        if missing := TOOLS - allowed:
            raise NsightError(
                f"Codex configuration hides tools: {sorted(missing)}", code="TOOLS_DISABLED"
            )
        command = server.get("command")
        if not command:
            raise NsightError("nsight requires a local STDIO command.", code="MCP_CONFIG_INVALID")
        result = run_probe(
            command,
            server.get("args", []),
            server.get("env"),
            timeout=float(server.get("tool_timeout_sec", 300)),
            report=report,
        )
        result["config_path"] = str(path.resolve())
        return result
    except Exception as exc:
        if isinstance(exc, NsightError):
            return exc.as_dict()
        return {
            "status": "error",
            "code": "MCP_CONFIG_INVALID",
            "message": str(exc),
            "recovery": "Run --setup to create a validated nsight configuration.",
        }
