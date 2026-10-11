"""Install this Python environment's MCP server into the user's Codex config."""

from __future__ import annotations

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


def render_config(original: str, python: str, nsys: str) -> str:
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
        "enabled = true\nstartup_timeout_sec = 30\ntool_timeout_sec = 300\n"
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


def configure_codex() -> dict:
    nsys = str(discover_nsys().resolve())
    python = str(Path(sys.executable).resolve())
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    path = home / "config.toml"
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    rendered = render_config(original, python, nsys)
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
        "tool_timeout_sec": 300,
        "next_step": "Restart/reconnect Codex MCP, then ask it to call nsight_doctor and list six tools.",
    }
