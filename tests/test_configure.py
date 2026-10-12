import json
import sys
import tomllib

import pytest

from nsight_agent.configure import configure_codex, render_config
from nsight_agent.core import NsightError


def test_new_config_sets_both_timeouts():
    config = tomllib.loads(render_config("", "C:\\中文 空格\\python.exe", "C:\\NVIDIA\\nsys.exe"))
    server = config["mcp_servers"]["nsight"]
    assert server["command"] == "C:\\中文 空格\\python.exe"
    assert server["startup_timeout_sec"] == 30
    assert server["tool_timeout_sec"] == 300


def test_update_keeps_unrelated_config_and_is_idempotent():
    original = """# User preference
model = "user-model"
[mcp_servers.other]
args = []
command = "keep-me"
[mcp_servers.nsight]
command = "old-python"
tool_timeout_sec = 60
[mcp_servers.nsight.env]
CUSTOM = "old"
[projects."C:/somewhere"]
trust_level = "trusted"
"""
    rendered = render_config(original, "new-python", "nsys")
    before, after = tomllib.loads(original), tomllib.loads(rendered)
    assert after["model"] == before["model"]
    assert after["mcp_servers"]["other"] == before["mcp_servers"]["other"]
    assert after["projects"] == before["projects"]
    assert rendered.startswith("# User preference")
    assert render_config(rendered, "new-python", "nsys") == rendered


def test_unusual_quoted_existing_table_fails_safely():
    with pytest.raises(NsightError, match="Cannot safely update"):
        render_config('[mcp_servers."nsight"]\ncommand="old"\n', "python", "nsys")


def test_invalid_original_toml_is_actionable():
    with pytest.raises(NsightError) as error:
        render_config("broken = [", "python", "nsys")
    assert error.value.code == "MCP_CONFIG_INVALID"
    assert "config.toml" in error.value.recovery
    assert isinstance(error.value.__cause__, tomllib.TOMLDecodeError)


def test_setup_cli_invalid_toml_preserves_original(tmp_path, monkeypatch, capsys):
    from nsight_agent.server import main

    config = tmp_path / "config.toml"
    original = b"broken = ["
    config.write_bytes(original)
    nsys = tmp_path / "nsys.exe"
    nsys.touch()
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr("nsight_agent.configure.discover_nsys", lambda: nsys)
    monkeypatch.setattr("nsight_agent.health.run_probe", lambda **kw: {"status": "connected"})
    monkeypatch.setattr(sys, "argv", ["nsight-agent", "--setup"])
    with pytest.raises(SystemExit) as exit_status:
        main()
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert exit_status.value.code == 1
    assert result["status"] == "error" and result["code"] == "MCP_CONFIG_INVALID"
    assert result["recovery"] and not output.err
    assert config.read_bytes() == original
    assert set(tmp_path.iterdir()) == {config, nsys}


def test_configure_backs_up_and_preserves_config(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    original = '# original\nmodel = "keep"\n'
    config.write_text(original, encoding="utf-8")
    nsys = tmp_path / "nsys.exe"
    nsys.touch()
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr("nsight_agent.configure.discover_nsys", lambda: nsys)
    result = configure_codex()
    assert result["status"] == "configured"
    assert tomllib.loads(config.read_text(encoding="utf-8"))["model"] == "keep"
    assert (tmp_path / result["backup_path"]).read_text(encoding="utf-8") == original


def test_complete_setup_config_requires_server_and_longer_timeout():
    config = tomllib.loads(render_config("", "python", "nsys", required=True, tool_timeout=600))
    server = config["mcp_servers"]["nsight"]
    assert server["required"] is True and server["tool_timeout_sec"] == 600


def test_setup_failure_keeps_existing_configuration(tmp_path, monkeypatch):
    from nsight_agent.configure import setup

    config = tmp_path / "config.toml"
    config.write_text('model="keep"\n')
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    nsys = tmp_path / "nsys.exe"
    nsys.touch()
    monkeypatch.setattr("nsight_agent.configure.discover_nsys", lambda: nsys)
    monkeypatch.setattr(
        "nsight_agent.health.run_probe", lambda **kw: {"status": "error", "code": "TOOLS_MISSING"}
    )
    assert setup()["code"] == "TOOLS_MISSING"
    assert config.read_text() == 'model="keep"\n'


def test_install_skill_preserves_custom_edits(tmp_path, monkeypatch):
    from nsight_agent.configure import install_analysis_skill

    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    first = install_analysis_skill()
    assert first["status"] == "installed"
    assert install_analysis_skill()["status"] == "unchanged"
    path = tmp_path / "skills/nsight-analysis/SKILL.md"
    path.write_text("user-customized skill", encoding="utf-8")
    assert install_analysis_skill()["status"] == "preserved_custom"
    assert path.read_text() == "user-customized skill"
