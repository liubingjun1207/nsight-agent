"""Run official Nsight reports; never query the raw profiling database."""

from __future__ import annotations

import csv
import hashlib
import io
import math
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

REPORTS = {
    "kernel_summary": "cuda_gpu_kern_sum",
    "kernel_trace": "cuda_gpu_trace",
    "cuda_api_summary": "cuda_api_sum",
    "memory_time": "cuda_gpu_mem_time_sum",
    "memory_size": "cuda_gpu_mem_size_sum",
}


class NsightError(RuntimeError):
    """An actionable error safe to surface through MCP."""


class Query(BaseModel):
    """Time and NVTX filters are exclusive. Times use report-relative nanoseconds."""

    model_config = ConfigDict(extra="forbid")
    start_ns: int | None = None
    end_ns: int | None = None
    nvtx: str | None = Field(default=None, min_length=1, max_length=1024)
    name_contains: str | None = Field(default=None, max_length=1024)
    sort_by: str | None = None
    descending: bool = True
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=200)

    @model_validator(mode="after")
    def check_range(self):
        if self.nvtx is not None and (self.start_ns is not None or self.end_ns is not None):
            raise ValueError("Choose a time range OR an NVTX range, not both.")
        if self.start_ns is not None and self.end_ns is not None:
            if self.start_ns > self.end_ns:
                raise ValueError("start_ns must be <= end_ns.")
        if self.nvtx and "\x00" in self.nvtx:
            raise ValueError("NVTX filter cannot contain NUL.")
        return self


@dataclass(frozen=True)
class Report:
    path: Path
    size: int
    mtime_ns: int


def discover_nsys(explicit: str | None = None) -> Path:
    configured = explicit or os.environ.get("NSIGHT_NSYS_PATH")
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_file():
            raise NsightError(f"NSIGHT_NSYS_PATH does not name a file: {path}")
        return path
    found = shutil.which("nsys")
    if found:
        return Path(found).resolve()
    root = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "NVIDIA Corporation"
    candidates = list(root.glob("Nsight Systems */target-windows-x64/nsys.exe"))
    if candidates:
        return max(
            candidates, key=lambda p: tuple(map(int, re.findall(r"\d+", p.parent.parent.name)))
        )
    raise NsightError("Nsight Systems CLI not found. Set NSIGHT_NSYS_PATH to nsys.exe.")


def parse_csv(text: str) -> tuple[list[str], list[dict]]:
    """Keep NVIDIA's column labels/units; preserve integer timestamp precision."""
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    columns = reader.fieldnames or []
    if not columns or not any(c in columns for c in ("Name", "Operation", "Kernel Name")):
        raise NsightError("Nsight returned no valid CSV table; report data may be missing.")
    if len(set(columns)) != len(columns):
        raise NsightError("Nsight returned duplicate CSV columns.")
    rows = []
    text_columns = {"Name", "Operation", "Kernel Name", "Device", "SrcMemKd", "DstMemKd"}
    for record in reader:
        if None in record or any(value is None for value in record.values()):
            raise NsightError("Malformed Nsight CSV row.")
        row = {}
        for key, value in record.items():
            if value == "":
                row[key] = None
            elif key in text_columns:
                row[key] = value
            elif re.fullmatch(r"-?\d+", value):
                row[key] = int(value)
            else:
                try:
                    number = float(value)
                    row[key] = number if math.isfinite(number) else value
                except ValueError:
                    row[key] = value
        rows.append(row)
    return columns, rows


def time_argument(value: int | None) -> str:
    """Avoid Nsight 2025.6's integer parser overflow for nanoseconds > 2^31."""
    if value is None:
        return ""
    seconds, nanos = divmod(abs(value), 1_000_000_000)
    return f"{'-' if value < 0 else ''}{seconds}.{nanos:09d}s"


def run_process(args: list[str], *, cwd: Path, env: dict, timeout: float):
    """Terminate Nsight's helper process tree as well as its launcher on timeout."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with subprocess.Popen(
        args,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        creationflags=flags,
        start_new_session=os.name != "nt",
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                try:
                    subprocess.run(
                        [
                            str(
                                Path(os.environ.get("SystemRoot", "C:/Windows"))
                                / "System32/taskkill.exe"
                            ),
                            "/PID",
                            str(process.pid),
                            "/T",
                            "/F",
                        ],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=10,
                        check=False,
                        creationflags=flags,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    process.kill()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process.poll() is None:
                process.kill()
            # Do not drain inherited helper pipes after a failed tree kill.
            process.wait(timeout=10)
            raise
    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)


class NsightService:
    def __init__(
        self, nsys: str | None = None, cache_dir: str | Path | None = None, timeout: float = 120
    ):
        self.explicit_nsys = nsys
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache"))
        self.cache = Path(cache_dir or os.environ.get("NSIGHT_CACHE_DIR", base / "nsight-agent"))
        self.timeout = timeout
        self.reports: dict[str, Report] = {}
        self._capabilities: dict | None = None
        self._lock = threading.RLock()
        self._session_cache: Path | None = None

    def _run(self, args: list[str], cwd: Path) -> str:
        env = os.environ.copy()
        # Nsight searches these paths for executable Python report scripts.
        env.pop("NSYS_STATS_REPORT_PATH", None)
        env.pop("PYTHONPATH", None)
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            result = run_process(
                [str(discover_nsys(self.explicit_nsys)), *args],
                cwd=cwd,
                env=env,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise NsightError(
                f"Nsight exceeded {self.timeout:g}s; narrow the query or increase NSIGHT_TIMEOUT_SECONDS."
            ) from exc
        except OSError as exc:
            raise NsightError(f"Cannot execute Nsight: {exc}") from exc
        # Nsight 2025.6 returns exit 1 for this successful discovery command.
        if (
            args == ["stats", "--help-reports"]
            and result.returncode == 1
            and "The following built-in reports are available:" in result.stdout
            and not result.stderr.strip()
        ):
            return result.stdout
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()[-3000:]
            raise NsightError(f"Nsight failed (exit {result.returncode}): {detail}")
        # Some Nsight reports skip missing data without failing the process.
        diagnostic = result.stderr.strip()
        if diagnostic:
            raise NsightError(f"Nsight diagnostic (result not accepted): {diagnostic[-3000:]}")
        return result.stdout

    def doctor(self) -> dict:
        with self._lock:
            self.cache.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="probe-", dir=self.cache) as directory:
                cwd = Path(directory)
                version = self._run(["--version"], cwd).strip()
                help_text = self._run(["stats", "--help"], cwd)
                report_text = self._run(["stats", "--help-reports"], cwd)
            available = re.findall(r"^\s+([a-z][a-z0-9_]+)(?:\[|\s+--)", report_text, re.M)
            options = sorted(set(re.findall(r"--[a-z][a-z-]+", help_text)))
            self._capabilities = {
                "nsys_path": str(discover_nsys(self.explicit_nsys)),
                "version": version,
                "reports": available,
                "options": options,
                "missing_reports": sorted(set(REPORTS.values()) - set(available)),
                "cache_dir": str(self.cache.resolve()),
            }
            return dict(self._capabilities)

    def open_report(self, path: str) -> dict:
        source = Path(path).expanduser().resolve()
        if not source.is_file() or source.suffix.lower() not in (".nsys-rep", ".sqlite"):
            raise NsightError("Expected an existing .nsys-rep or Nsight-exported .sqlite file.")
        stat = source.stat()
        if stat.st_size == 0:
            raise NsightError("Report file is empty.")
        identity = f"{source}\0{stat.st_size}\0{stat.st_mtime_ns}"
        report_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
        with self._lock:
            self.reports[report_id] = Report(source, stat.st_size, stat.st_mtime_ns)
        return {
            "report_id": report_id,
            "path": str(source),
            "size_bytes": stat.st_size,
            "status": "registered",
            "note": "Data availability is validated by Nsight on first query. IDs last for this server session.",
        }

    def _check_source(self, report: Report):
        if not report.path.is_file():
            raise NsightError("Report no longer exists; reopen the report.")
        stat = report.path.stat()
        if (stat.st_size, stat.st_mtime_ns) != (report.size, report.mtime_ns):
            raise NsightError("Report changed since registration; reopen it before querying.")

    def _table(self, report_id: str, report_name: str, query: Query):
        capabilities = self._capabilities or self.doctor()
        if report_name not in capabilities["reports"]:
            raise NsightError(f"Installed Nsight does not support {report_name}.")
        required = {"--report", "--format", "--output", "--quiet"}
        if query.nvtx is not None:
            required.add("--filter-nvtx")
        if query.start_ns is not None or query.end_ns is not None:
            required.add("--filter-time")
        if not required.issubset(capabilities["options"]):
            raise NsightError(
                f"Unsupported Nsight options: {sorted(required - set(capabilities['options']))}"
            )
        report = self.reports.get(report_id)
        if report is None:
            raise NsightError("Unknown report_id; call nsight_open_report first.")
        self._check_source(report)
        if self._session_cache is None:
            self.cache.mkdir(parents=True, exist_ok=True)
            self._session_cache = Path(tempfile.mkdtemp(prefix="session-", dir=self.cache))
        workspace = self._session_cache / report_id
        workspace.mkdir(parents=True, exist_ok=True)
        # Never let Nsight open the original SQLite, even if it creates sidecars.
        local = workspace / ("input" + report.path.suffix.lower())
        if not local.exists():
            partial = workspace / "input.partial"
            shutil.copyfile(report.path, partial)
            self._check_source(report)
            partial.replace(local)
        if local.suffix == ".nsys-rep":
            exported = workspace / "export.sqlite"
            if not exported.exists():
                # Export to a temporary directory so failed/partial exports are never reused.
                with tempfile.TemporaryDirectory(prefix="export-", dir=workspace) as directory:
                    temporary = Path(directory) / "report.sqlite"
                    self._run(
                        [
                            "export",
                            "--type=sqlite",
                            "--quiet=true",
                            f"--output={temporary.resolve()}",
                            str(local.resolve()),
                        ],
                        Path(directory),
                    )
                    if not temporary.is_file():
                        raise NsightError("Nsight export did not create a SQLite report.")
                    temporary.replace(exported)
            local = exported
        args = [
            "stats",
            "--report",
            report_name,
            "--format",
            "csv:time=ns:bytes=B",
            "--output",
            "-",
            "--quiet",
        ]
        if query.nvtx is not None:
            args += [f"--filter-nvtx={query.nvtx}"]
        elif query.start_ns is not None or query.end_ns is not None:
            start = time_argument(query.start_ns)
            end = time_argument(query.end_ns)
            args += [f"--filter-time={start}/{end}"]
        args.append(str(local.resolve()))
        # An empty working directory prevents shadowing NVIDIA's built-in reports.
        with tempfile.TemporaryDirectory(prefix="run-", dir=self.cache) as directory:
            stdout = self._run(args, Path(directory))
        columns, rows = parse_csv(stdout)
        return columns, rows, capabilities, args

    def query(self, report_id: str, kind: str, query: Query | None = None) -> dict:
        if kind not in REPORTS:
            raise NsightError("Unsupported analysis kind.")
        query = query or Query()
        with self._lock:
            report_name = REPORTS[kind]
            columns, rows, capabilities, args = self._table(report_id, report_name, query)
            if kind == "kernel_trace":
                if "GrdX" not in columns:
                    raise NsightError(
                        "Unsupported trace schema: missing GrdX kernel discriminator."
                    )
                rows = [row for row in rows if row["GrdX"] is not None]
            name_column = "Operation" if "Operation" in columns else "Name"
            if query.name_contains is not None:
                rows = [
                    row
                    for row in rows
                    if query.name_contains.casefold() in str(row[name_column]).casefold()
                ]
            defaults = {"kernel_trace": "Duration (ns)", "memory_size": "Total (B)"}
            sort_by = query.sort_by or defaults.get(kind, "Total Time (ns)")
            if sort_by not in columns:
                raise NsightError(f"Unknown sort column {sort_by!r}. Available columns: {columns}")
            present = [r for r in rows if r[sort_by] is not None]
            missing = [r for r in rows if r[sort_by] is None]
            try:
                rows = sorted(present, key=lambda r: r[sort_by], reverse=query.descending) + missing
            except TypeError as exc:
                raise NsightError(
                    f"Nsight returned incompatible types for sort column {sort_by}."
                ) from exc
            total = len(rows)
            page = rows[query.offset : query.offset + query.limit]
            next_offset = query.offset + len(page)
            return {
                "report_id": report_id,
                "nsight_version": capabilities["version"],
                "official_report": report_name,
                "filters": query.model_dump(),
                "sort_by": sort_by,
                "columns": columns,
                "units": {"time": "ns", "memory": "B", "throughput": "B/s", "ratio": "%"},
                "rows": page,
                "total_rows": total,
                "offset": query.offset,
                "next_offset": next_offset if next_offset < total else None,
                "provenance": {"executable": capabilities["nsys_path"], "arguments": args},
                "semantics": [
                    "Nsight includes events overlapping the selected range; event durations are not clipped.",
                    "Time (%) retains Nsight's denominator before name filtering and pagination.",
                    "Kernel cumulative time is neither application wall time nor GPU utilization.",
                    "CUDA API durations measure CPU calls, not GPU kernel execution.",
                    "No matching rows does not prove zero activity outside the recorded data.",
                ],
            }

    def memory_summary(
        self, report_id: str, metric: Literal["time", "size"], query: Query | None = None
    ):
        if metric not in ("time", "size"):
            raise NsightError("metric must be 'time' or 'size'.")
        return self.query(report_id, f"memory_{metric}", query)
