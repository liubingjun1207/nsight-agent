"""Install this Python environment's MCP server into the user's Codex config."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import sys
import tempfile
import tomllib
from datetime import datetime
from pathlib import Path

from .core import NsightError, discover_nsys


def render_config(
    original: str, python: str, nsys: str, *, required=False, tool_timeout=300
) -> str:
    """Replace only the nsight table family, preserving unrelated TOML text and meaning."""
    before = tomllib.loads(original)
    sections = re.split(r"(?m)(?=^[ \t]*\[)", original)
    kept = []
    for section in sections:
        header = section.splitlines()[0].strip() if section else ""
        if re.fullmatch(r"\[mcp_servers\.nsight(?:\.[A-Za-z0-9_-]+)*\]\s*(?:#.*)?", header):
            continue
        kept.append(section)
    block = (
        "\n[mcp_servers.nsight]\n"
        f"command = {json.dumps(python, ensure_ascii=False)}\n"
        'args = ["-m", "nsight_agent"]\n'
        "enabled = true\nstartup_timeout_sec = 30\n"
        f"required = {'true' if required else 'false'}\ntool_timeout_sec = {tool_timeout}\n"
        "\n[mcp_servers.nsight.env]\n"
        f"NSIGHT_NSYS_PATH = {json.dumps(nsys, ensure_ascii=False)}\n"
        'NSIGHT_TIMEOUT_SECONDS = "120"\nPYTHONIOENCODING = "utf-8"\n'
    )
    result = "".join(kept).rstrip() + "\n" + block
    try:
        after = tomllib.loads(result)
    except tomllib.TOMLDecodeError as exc:
        raise NsightError(
            "Cannot safely update the existing nsight configuration; edit its table manually."
        ) from exc
    expected = {**before, "mcp_servers": dict(before.get("mcp_servers", {}))}
    expected["mcp_servers"].pop("nsight", None)
    actual = {**after, "mcp_servers": dict(after.get("mcp_servers", {}))}
    actual["mcp_servers"].pop("nsight", None)
    if expected != actual:
        raise NsightError(
            "Configuration update would change unrelated settings; no file was written."
        )
    return result


def configure_codex(*, required=False, tool_timeout=300) -> dict:
    nsys = str(discover_nsys().resolve())
    python = str(Path(sys.executable).resolve())
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    path = home / "config.toml"
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    rendered = render_config(original, python, nsys, required=required, tool_timeout=tool_timeout)
    home.mkdir(parents=True, exist_ok=True)
    backup = None
    if path.exists():
        backup = path.with_name(f"config.toml.before-nsight-{datetime.now():%Y%m%d-%H%M%S-%f}.bak")
        shutil.copy2(path, backup)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=home, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(rendered)
    try:
        # Abort rather than overwrite a configuration edited by another client meanwhile.
        latest = path.read_text(encoding="utf-8") if path.exists() else ""
        if latest != original:
            raise NsightError("Codex configuration changed during setup; retry the command.")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "status": "configured",
        "config_path": str(path),
        "backup_path": str(backup) if backup else None,
        "server": "nsight",
        "python": python,
        "nsys": nsys,
        "startup_timeout_sec": 30,
        "tool_timeout_sec": tool_timeout,
        "required": required,
        "next_step": "Restart/reconnect Codex MCP; call nsight_capabilities and verify twelve tools.",
    }


def install_analysis_skill() -> dict:
    source = None
    for item in importlib.metadata.distribution("nsight-agent").files or []:
        if str(item).replace("\\", "/").endswith("skills/nsight-analysis/SKILL.md"):
            candidate = Path(item.locate())
            if candidate.is_file():
                source = candidate
                break
    if source is None:
        source = Path(__file__).resolve().parents[2] / "skills/nsight-analysis/SKILL.md"
    if not source.is_file():
        raise NsightError(
            "Packaged analysis skill not found; reinstall the complete package.",
            code="INSTALLATION_INCOMPLETE",
        )
    content = source.read_bytes()
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    directory = home / "skills/nsight-analysis"
    target, marker = directory / "SKILL.md", directory / ".nsight-agent.sha256"
    if target.exists():
        current = hashlib.sha256(target.read_bytes()).hexdigest()
        if current == hashlib.sha256(content).hexdigest():
            return {"status": "unchanged", "path": str(target)}
        if not marker.exists() or marker.read_text().strip() != current:
            return {
                "status": "preserved_custom",
                "path": str(target),
                "note": "Existing unrecognized or edited skill preserved; review it before upgrading manually.",
            }
    directory.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    marker.write_text(hashlib.sha256(content).hexdigest() + "\n", encoding="utf-8")
    return {"status": "installed", "path": str(target)}


def setup() -> dict:
    from .health import run_probe

    nsys = str(discover_nsys().resolve())
    checked = run_probe(env={"NSIGHT_NSYS_PATH": nsys, "PYTHONIOENCODING": "utf-8"})
    if checked["status"] != "connected":
        return checked
    configured = configure_codex(required=True, tool_timeout=600)
    return {
        "status": "ready_limited" if checked.get("missing_reports") else "ready",
        "connection": checked,
        "configuration": configured,
        "skill": install_analysis_skill(),
        "next_step": "Reconnect/restart Codex, then try the documented analysis workflow.",
    }
