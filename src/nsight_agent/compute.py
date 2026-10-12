"""Optional Nsight Compute report import through a fixed metric catalog."""

from __future__ import annotations

import csv
import hashlib
import io
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MetricGroup = Literal["occupancy", "throughput", "memory", "stalls", "launch"]
STALL_REASONS = (
    "barrier",
    "long_scoreboard",
    "short_scoreboard",
    "math_pipe_throttle",
    "mio_throttle",
    "lg_throttle",
    "not_selected",
    "wait",
    "membar",
    "no_instruction",
)
METRICS = {
    "occupancy": (
        "sm__warps_active.avg.pct_of_peak_sustained_active",
        "sm__warps_active.avg.per_cycle_active",
        "launch__occupancy_limit_blocks",
        "launch__occupancy_limit_registers",
        "launch__occupancy_limit_shared_mem",
        "launch__occupancy_limit_warps",
    ),
    "throughput": (
        "sm__throughput.avg.pct_of_peak_sustained_elapsed",
        "gpu__compute_memory_throughput.avg.pct_of_peak_sustained_elapsed",
        "gpu__dram_throughput.avg.pct_of_peak_sustained_elapsed",
        "dram__throughput.avg.pct_of_peak_sustained_elapsed",
        "lts__throughput.avg.pct_of_peak_sustained_elapsed",
        "l1tex__throughput.avg.pct_of_peak_sustained_elapsed",
    ),
    "memory": (
        "dram__bytes.sum",
        "dram__bytes.sum.per_second",
        "dram__bytes_read.sum",
        "dram__bytes_write.sum",
        "lts__t_sector_hit_rate.pct",
        "l1tex__t_sector_hit_rate.pct",
    ),
    "stalls": tuple(
        metric
        for reason in STALL_REASONS
        for metric in (
            f"smsp__average_warps_issue_stalled_{reason}_per_issue_active.ratio",
            f"smsp__warp_issue_stalled_{reason}_per_warp_active.pct",
        )
    ),
    "launch": (
        "gpu__time_duration.sum",
        "launch__registers_per_thread",
        "launch__shared_mem_per_block",
        "launch__block_size",
        "launch__grid_size",
    ),
}


class ComputeQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name_contains: str | None = Field(default=None, max_length=1024)
    kernel_id: str | None = Field(default=None, min_length=1, max_length=128)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=200)


def discover_ncu(explicit=None):
    from .core import NsightError

    configured = explicit or os.environ.get("NSIGHT_NCU_PATH")
    if configured:
        path = Path(configured).expanduser().resolve()
        if path.is_file():
            return path
    else:
        if found := shutil.which("ncu"):
            return Path(found).resolve()
        root = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "NVIDIA Corporation"
        candidates = list(root.glob("Nsight Compute */target/windows-desktop-win7-x64/ncu.exe"))
        if candidates:
            return max(
                candidates, key=lambda p: tuple(map(int, re.findall(r"\d+", p.parents[2].name)))
            )
    raise NsightError(
        "Nsight Compute CLI not found or NSIGHT_NCU_PATH is invalid.",
        code="NCU_NOT_FOUND",
        recovery="Install Nsight Compute or set NSIGHT_NCU_PATH to its executable; "
        "Systems analysis remains available without Compute.",
    )


def parse_compute_csv(text, requested):
    from .core import NsightError

    records = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    if len(records) < 2 or not {"ID", "Kernel Name", "Device"}.issubset(records[0]):
        raise NsightError("Nsight Compute returned no valid CSV table.", code="MISSING_DATA")
    columns, units = records[:2]
    if len(set(columns)) != len(columns) or len(units) != len(columns):
        raise NsightError("Unsupported Compute CSV schema: invalid columns/unit row.")
    indices = {name: i for i, name in enumerate(columns)}
    if units[indices["ID"]] or units[indices["Kernel Name"]]:
        raise NsightError("Unsupported Compute CSV schema: expected a separate units row.")
    available = [name for name in requested if name in indices]
    if not available:
        raise NsightError(
            "No requested metrics were collected in this Compute report.",
            code="MISSING_DATA",
            recovery="Select another metric group or collect the required Compute sections; "
            "missing hardware metrics cannot be recovered from a Systems report.",
        )
    rows = []
    for record in records[2:]:
        if not record:
            continue
        if len(record) != len(columns) or not record[indices["ID"]]:
            raise NsightError("Unsupported Compute CSV schema: malformed kernel row.")
        for metric in available:
            value = record[indices[metric]]
            numeric = None
            if re.fullmatch(r"[+-]?\d+(?:,\d{3})*", value):
                numeric = int(value.replace(",", ""))
            else:
                try:
                    number = float(value.replace(",", ""))
                    numeric = number if math.isfinite(number) else None
                except ValueError:
                    pass
            rows.append(
                {
                    "Kernel ID": record[indices["ID"]],
                    "Kernel Name": record[indices["Kernel Name"]],
                    "Device": record[indices["Device"]],
                    "Metric Name": metric,
                    "Metric Unit": units[indices[metric]],
                    "Metric Value": numeric,
                    "Raw Value": value,
                    "measurement_status": "measured" if numeric is not None else "unavailable",
                }
            )
    return rows, available


class ComputeMixin:
    def _run_compute(self, args, cwd):
        from .core import NsightError, run_process

        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            result = run_process(
                [str(discover_ncu()), "--config-file", "off", *args],
                cwd=cwd,
                env=env,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise NsightError(f"Nsight Compute exceeded {self.timeout:g}s.") from exc
        except OSError as exc:
            raise NsightError(
                f"Cannot execute Nsight Compute: {exc}", code="COMMAND_FAILED"
            ) from exc
        if result.returncode or re.search(
            r"(?im)^\s*(?:==|\[)?(?:ERROR|FATAL)(?:==|\]|\b)",
            result.stderr + "\n" + result.stdout,
        ):
            raise NsightError(
                f"Nsight failed importing Compute report (exit {result.returncode}): "
                f"{(result.stderr or result.stdout)[-3000:]}",
                code="COMMAND_FAILED",
            )
        if result.stderr.strip():
            self._warnings.append({"arguments": args, "message": result.stderr.strip()[-3000:]})
        return result.stdout

    def compute_doctor(self):
        with self._lock, self._cache_io():
            executable = discover_ncu()
            self.cache.mkdir(parents=True, exist_ok=True)
            self._warnings = []
            with tempfile.TemporaryDirectory(prefix="compute-probe-", dir=self.cache) as directory:
                version = self._run_compute(["--version"], Path(directory)).strip()
                help_text = self._run_compute(["--help"], Path(directory))
            required = {
                "--import",
                "--csv",
                "--page",
                "--metrics",
                "--print-units",
                "--config-file",
            }
            missing = sorted(required - set(re.findall(r"--[a-z][a-z-]+", help_text)))
            self._compute_capabilities = {
                "version": version,
                "ncu_path": str(executable),
                "metric_groups": METRICS,
                "missing_options": missing,
                "warnings": list(self._warnings),
                "note": "Optional report reader only: no Compute collection or arbitrary metrics. "
                "Metric availability depends on the report, GPU and collector version.",
            }
            return dict(self._compute_capabilities)

    def compute_open_report(self, path):
        from .core import NsightError, Report

        source = Path(path).expanduser().resolve()
        if not source.is_file() or source.suffix.lower() != ".ncu-rep":
            raise NsightError(
                "Expected an existing .ncu-rep report.",
                code="INVALID_COMPUTE_REPORT",
                recovery="Provide a local Nsight Compute report; .nsys-rep is a different format.",
            )
        stat = source.stat()
        if not stat.st_size:
            raise NsightError("Compute report is empty.", code="INVALID_COMPUTE_REPORT")
        identity = f"{source}:{stat.st_size}:{stat.st_mtime_ns}"
        report_id = "ncu-" + hashlib.sha256(identity.encode()).hexdigest()[:24]
        with self._lock:
            self._compute_reports[report_id] = Report(source, stat.st_size, stat.st_mtime_ns)
        return {"report_id": report_id, "path": str(source), "status": "registered"}

    def compute_metrics(self, report_id, group="occupancy", query=None):
        from .core import NsightError

        if group not in METRICS:
            raise NsightError("Unsupported Compute metric group.", code="OUT_OF_SCOPE")
        query = query or ComputeQuery()
        with self._lock, self._cache_io():
            capabilities = self._compute_capabilities or self.compute_doctor()
            if capabilities["missing_options"]:
                raise NsightError(f"Unsupported Nsight options: {capabilities['missing_options']}")
            source = self._compute_reports.get(report_id)
            if source is None:
                raise NsightError("Unknown report_id; call nsight_compute_open_report first.")
            self._check_source(source)
            self._warnings = []
            self.cache.mkdir(parents=True, exist_ok=True)
            if self._session_cache is None:
                self._session_cache = Path(tempfile.mkdtemp(prefix="session-", dir=self.cache))
            workspace = self._session_cache / report_id
            workspace.mkdir(parents=True, exist_ok=True)
            local = workspace / "input.ncu-rep"
            if not local.exists():
                partial = workspace / "input.partial"
                shutil.copyfile(source.path, partial)
                self._check_source(source)
                partial.replace(local)
            args = [
                "--import",
                str(local.resolve()),
                "--csv",
                "--page",
                "raw",
                "--print-units",
                "base",
                "--metrics",
                ",".join(METRICS[group]),
            ]
            with tempfile.TemporaryDirectory(prefix="compute-run-", dir=self.cache) as directory:
                stdout = self._run_compute(args, Path(directory))
            rows, available = parse_compute_csv(stdout, METRICS[group])
            if query.name_contains is not None:
                rows = [
                    r for r in rows if query.name_contains.casefold() in r["Kernel Name"].casefold()
                ]
            if query.kernel_id is not None:
                rows = [r for r in rows if r["Kernel ID"] == query.kernel_id]
            page = rows[query.offset : query.offset + query.limit]
            end = query.offset + len(page)
            return self._remember(
                {
                    "report_id": report_id,
                    "engine": "nsight_compute",
                    "metric_group": group,
                    "nsight_version": capabilities["version"],
                    "source": {
                        "path": str(source.path),
                        "size_bytes": source.size,
                        "mtime_ns": source.mtime_ns,
                    },
                    "filters": query.model_dump(),
                    "columns": [
                        "Kernel ID",
                        "Kernel Name",
                        "Device",
                        "Metric Name",
                        "Metric Unit",
                        "Metric Value",
                        "Raw Value",
                        "measurement_status",
                    ],
                    "rows": page,
                    "total_rows": len(rows),
                    "offset": query.offset,
                    "next_offset": end if end < len(rows) else None,
                    "available_metrics": available,
                    "missing_metrics": [name for name in METRICS[group] if name not in available],
                    "provenance": {
                        "executable": capabilities["ncu_path"],
                        "arguments": ["--config-file", "off", *args],
                    },
                    "warnings": list(self._warnings),
                    "semantics": [
                        "Values and units are from the imported Compute capture; absent/invalid values are not zero.",
                        "Occupancy, resource throughput and sampled stalls are distinct; high occupancy need not mean faster execution.",
                        "Stall ratio and percentage variants have different denominators; retain the exact metric and unit.",
                        "Compute replay/instrumentation can alter timing. Do not substitute it for Systems wall-time evidence.",
                        "Kernel IDs belong to this capture. No automatic matching to another Systems/Compute capture is performed.",
                    ],
                }
            )
