"""Configured environments and working directories must reach the real STDIO child."""

import json
import sys

import pytest

from nsight_agent.core import NsightError
from nsight_agent.health import TOOLS, check_connection, configured_environment


def test_configured_environment_whitelist_and_explicit_precedence(monkeypatch):
    monkeypatch.setenv("NSIGHT_TEST_FORWARD", "inherited")
    monkeypatch.setenv("NSIGHT_TEST_UNLISTED", "do-not-forward")
    monkeypatch.delenv("NSIGHT_TEST_MISSING", raising=False)
    assert configured_environment({"env_vars": ["NSIGHT_TEST_FORWARD", "NSIGHT_TEST_MISSING"]}) == {
        "NSIGHT_TEST_FORWARD": "inherited",
    }
    assert configured_environment(
        {
            "env_vars": [{"name": "NSIGHT_TEST_FORWARD", "source": "local"}],
            "env": {"NSIGHT_TEST_FORWARD": "explicit", "OTHER": "literal"},
        }
    ) == {"NSIGHT_TEST_FORWARD": "explicit", "OTHER": "literal"}


@pytest.mark.parametrize(
    "config",
    [
        {"env_vars": "PATH"},
        {"env": {"X": 3}},
        {"env_vars": [42]},
        {"env_vars": [{"source": "local"}]},
        {"env_vars": [{"name": "X", "source": "remote"}]},
        {"experimental_environment": "remote"},
    ],
)
def test_invalid_or_remote_environment_never_reports_local_success(config):
    with pytest.raises(NsightError) as error:
        configured_environment(config)
    assert error.value.code == "MCP_CONFIG_INVALID"


def test_check_forwards_configured_environment_and_cwd(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    cwd = tmp_path / "中文 工作目录"
    cwd.mkdir()
    monkeypatch.setenv("NSIGHT_TEST_FORWARD", "forwarded")
    config.write_text(
        '[mcp_servers.nsight]\ncommand="python"\nargs=["entry.py"]\n'
        'env_vars=["NSIGHT_TEST_FORWARD"]\n'
        f"cwd={json.dumps(str(cwd))}\n"
        '[mcp_servers.nsight.env]\nEXPLICIT="configured"\n',
        encoding="utf-8",
    )
    observed = {}

    def run(command, args, env, **kwargs):
        observed.update(command=command, args=args, env=env, **kwargs)
        return {"status": "connected"}

    monkeypatch.setattr("nsight_agent.health.run_probe", run)
    assert check_connection(config_path=config)["status"] == "connected"
    assert observed["env"] == {"NSIGHT_TEST_FORWARD": "forwarded", "EXPLICIT": "configured"}
    assert observed["cwd"] == str(cwd) and observed["args"] == ["entry.py"]


def test_env_vars_invalid_nsight_path_fails_real_stdio(tmp_path, monkeypatch):
    monkeypatch.setenv("NSIGHT_NSYS_PATH", str(tmp_path / "missing-nsys"))
    config = tmp_path / "config.toml"
    config.write_text(
        "[mcp_servers.nsight]\n"
        f"command={json.dumps(sys.executable)}\n"
        'args=["-m","nsight_agent"]\nenv_vars=["NSIGHT_NSYS_PATH"]\n',
        encoding="utf-8",
    )
    result = check_connection(config_path=config)
    assert result["status"] == "error" and result["code"] == "NSIGHT_CHECK_FAILED"
    assert "missing-nsys" in result["message"]


def test_cwd_and_env_vars_reach_actual_child(tmp_path, monkeypatch):
    cwd = tmp_path / "中文 工作目录"
    cwd.mkdir()
    (cwd / "marker.txt").write_text("correct cwd", encoding="utf-8")
    # The command is intentionally relative and the child depends on both cwd and env_vars.
    (cwd / "entry.py").write_text(
        "import os\nfrom pathlib import Path\nfrom typing import Any\n"
        "assert Path('marker.txt').read_text(encoding='utf-8') == 'correct cwd'\n"
        "assert os.environ['NSIGHT_TEST_FORWARD'] == 'forwarded'\n"
        "from mcp.server.fastmcp import FastMCP\n"
        "server = FastMCP('fixture')\n"
        "def doctor() -> dict[str, Any]: return {'version': 'fixture'}\n"
        "def capabilities() -> dict[str, Any]: return {'reports': []}\n"
        f"tools={sorted(TOOLS)!r}\n"
        "for name in tools:\n"
        "    function = capabilities if name == 'nsight_capabilities' else doctor\n"
        "    server.add_tool(function, name=name)\n"
        "server.run(transport='stdio')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NSIGHT_TEST_FORWARD", "forwarded")
    config = tmp_path / "config.toml"
    config.write_text(
        "[mcp_servers.nsight]\n"
        f'command={json.dumps(sys.executable)}\nargs=["entry.py"]\n'
        f'cwd={json.dumps(str(cwd))}\nenv_vars=["NSIGHT_TEST_FORWARD"]\n',
        encoding="utf-8",
    )
    result = check_connection(config_path=config)
    assert result["status"] == "connected" and result["nsight_version"] == "fixture", result
