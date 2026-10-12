"""Local collection of administrator-configured tasks, never model-supplied commands."""

from __future__ import annotations

import os
import re
import tempfile
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class CaptureTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    description: str = Field(default="", max_length=1000)
    command: list[str] = Field(min_length=1, max_length=100)
    cwd: str
    duration_seconds: int = Field(default=30, ge=1, le=120)
    timeout_seconds: int = Field(default=120, ge=30, le=300)

    @model_validator(mode="after")
    def validate_target(self):
        if not Path(self.cwd).is_absolute() or not Path(self.command[0]).is_absolute():
            raise ValueError("cwd and command[0] must be absolute paths")
        if any("\x00" in arg or len(arg) > 8192 for arg in self.command):
            raise ValueError("command arguments cannot contain NUL or exceed 8192 characters")
        if self.timeout_seconds < self.duration_seconds + 15:
            raise ValueError("timeout_seconds must allow at least 15s beyond duration_seconds")
        return self


def load_targets():
    from .core import NsightError

    configured = os.environ.get("NSIGHT_CAPTURE_CONFIG")
    if not configured:
        return {}
    path = Path(configured).expanduser()
    try:
        if not path.is_absolute():
            raise ValueError("NSIGHT_CAPTURE_CONFIG must be an absolute path")
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        if set(data) != {"targets"} or not isinstance(data["targets"], dict):
            raise ValueError("expected only a [targets.<name>] registry")
        if len(data["targets"]) > 100:
            raise ValueError("at most 100 targets may be registered")
        if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) for name in data["targets"]):
            raise ValueError(
                "target names must contain 1-64 letters, digits, underscores or hyphens"
            )
        return {name: CaptureTarget(**target) for name, target in data["targets"].items()}
    except (OSError, ValueError, TypeError, ValidationError) as exc:
        raise NsightError(
            f"Invalid capture registry {path}: {exc}",
            code="CAPTURE_CONFIG_INVALID",
            recovery="Fix the local TOML target registry, use absolute executable/cwd paths, "
            "and set NSIGHT_CAPTURE_CONFIG to its absolute path.",
        ) from exc


class CaptureMixin:
    def capture_targets(self):
        targets = load_targets()
        return {
            "status": "configured" if targets else "not_configured",
            "targets": [
                {"target_id": name, **target.model_dump()} for name, target in targets.items()
            ],
            "note": "Collection launches only configured local applications. It may use GPU "
            "resources and create application files. No command/arguments can be supplied by a tool call.",
            "recovery": "Create a capture target registry and set NSIGHT_CAPTURE_CONFIG "
            "in the MCP server environment; reconnect the server.",
        }

    def capture(self, target_id: str):
        from .core import NsightError

        target = load_targets().get(target_id)
        if target is None:
            raise NsightError(
                f"Unknown capture target {target_id!r}.",
                code="CAPTURE_TARGET_UNKNOWN",
                recovery="Call nsight_capture_targets and select an existing configured target; "
                "the service cannot accept a new executable through a tool call.",
            )
        if not Path(target.command[0]).is_file() or not Path(target.cwd).is_dir():
            raise NsightError(
                "Configured capture executable or working directory does not exist.",
                code="CAPTURE_TARGET_INVALID",
                recovery="Repair the executable/cwd paths in the local capture registry.",
            )
        with self._lock, self._cache_io():
            self.cache.mkdir(parents=True, exist_ok=True)
            self._warnings = []
            with tempfile.TemporaryDirectory(prefix="capture-probe-", dir=self.cache) as probe:
                version = self._run(["--version"], Path(probe)).strip()
                help_text = self._run(["profile", "--help"], Path(probe))
            required = {"--trace", "--sample", "--cpuctxsw", "--duration", "--kill", "--output"}
            if missing := required - set(re.findall(r"--[a-z][a-z-]+", help_text)):
                raise NsightError(f"Unsupported Nsight options: {sorted(missing)}")
            kill_help = re.search(r"--kill=.*?(?=\n\s*--|\Z)", help_text, re.S)
            values = kill_help.group() if kill_help else ""
            kill = "true" if "'true'" in values else "sigkill" if "'sigkill'" in values else None
            if kill is None:
                raise NsightError(
                    "Installed Nsight does not support a recognized capture termination policy."
                )
            directory = Path(tempfile.mkdtemp(prefix="capture-", dir=self.cache))
            output = directory / "capture"
            args = [
                "profile",
                "--trace=cuda,nvtx",
                "--sample=none",
                "--cpuctxsw=none",
                f"--duration={target.duration_seconds}",
                f"--kill={kill}",
                f"--output={output.resolve()}",
                *target.command,
            ]
            previous_timeout = self.timeout
            try:
                self.timeout = target.timeout_seconds
                self._run(args, Path(target.cwd))
            finally:
                self.timeout = previous_timeout
            report = output.with_suffix(".nsys-rep")
            if not report.is_file() or report.stat().st_size == 0:
                raise NsightError(
                    "Nsight collection did not produce a nonempty report.",
                    code="CAPTURE_FAILED",
                    recovery="Check the configured workload and CUDA/NVTX tracing support; "
                    "partial capture files are not registered.",
                )
            registered = self.open_report(str(report))
            return {
                **registered,
                "status": "captured",
                "target_id": target_id,
                "nsight_version": version,
                "duration_limit_seconds": target.duration_seconds,
                "command_timeout_seconds": target.timeout_seconds,
                "provenance": {"arguments": args, "cwd": target.cwd},
                "warnings": list(self._warnings),
                "note": "A duration limit can stop the application before completion. "
                "Collection is local to this MCP server; capture overhead changes measured timing.",
            }
