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

from .analysis import AnalysisMixin
from .catalog import CATALOG, CatalogMixin, ReportOptions

REPORTS = {
    "kernel_summary": "cuda_gpu_kern_sum",
    "kernel_trace": "cuda_gpu_trace",
    "cuda_api_summary": "cuda_api_sum",
    "memory_time": "cuda_gpu_mem_time_sum",
    "memory_size": "cuda_gpu_mem_size_sum",
}
OPTIONAL_REPORTS = {"nvtx_summary": "nvtx_sum", "nvtx_trace": "nvtx_pushpop_trace"}
ALL_REPORTS = REPORTS | OPTIONAL_REPORTS


class NsightError(RuntimeError):
    """An actionable error safe to surface through MCP."""

    def __init__(self, message: str, *, code: str | None = None):
        mappings = [
            (
                "CLI not found",
                "NSIGHT_NOT_FOUND",
                "Install Nsight Systems or set NSIGHT_NSYS_PATH.",
            ),
            (
                "does not support",
                "CAPABILITY_UNAVAILABLE",
                "Call nsight_capabilities; use an available report or a compatible reader.",
            ),
            (
                "Unsupported Nsight options",
                "CAPABILITY_UNAVAILABLE",
                "Check nsight_doctor and the installed Nsight version.",
            ),
            (
                "no valid CSV",
                "MISSING_DATA",
                "Check capture traces and range filters; missing data is not zero activity.",
            ),
            (
                "Unknown report_id",
                "REPORT_ID_EXPIRED",
                "Open the report again in this server session.",
            ),
            (
                "expired result_id",
                "RESULT_ID_EXPIRED",
                "Rerun the analysis and use its new result_id.",
            ),
            ("changed since", "REPORT_CHANGED", "Reopen the changed report."),
            (
                "Expected an existing",
                "INVALID_REPORT",
                "Provide an existing absolute .nsys-rep or exported .sqlite path.",
            ),
            ("exceeded", "TIMEOUT", "Narrow the range or increase both command and tool timeouts."),
            (
                "Nsight failed",
                "COMMAND_FAILED",
                "Check the Nsight diagnostic and try the same report in the local reader.",
            ),
            (
                "schema",
                "SCHEMA_INCOMPATIBLE",
                "Check the installed Nsight version and report columns.",
            ),
        ]
        matched = next((item for item in mappings if item[0] in message), None)
        self.code = code or (matched[1] if matched else "NSIGHT_ERROR")
        self.recovery = (
            matched[2]
            if matched
            else "Check the error detail and tool parameters; do not treat this as a zero measurement."
        )
        self.detail = message
        super().__init__(f"[{self.code}] {message} Recovery: {self.recovery}")

    def as_dict(self):
        return {
            "status": "error",
            "code": self.code,
            "message": self.detail,
            "recovery": self.recovery,
        }


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


class NvtxTraceQuery(Query):
    """NVTX discovery defaults to chronological order."""

    descending: bool = False


class StatsQuery(Query):
    """Use each official report's sort direction when not explicitly supplied."""

    descending: bool | None = None


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


def parse_csv(text: str, required: set[str] | None = None) -> tuple[list[str], list[dict]]:
    """Keep NVIDIA's column labels/units; preserve integer timestamp precision."""
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    columns = reader.fieldnames or []
    if not columns or not any(c in columns for c in ("Name", "Operation", "Kernel Name", "Range")):
        raise NsightError("Nsight returned no valid CSV table; report data may be missing.")
    if required and not required.issubset(columns):
        raise NsightError(f"Unsupported report schema: missing {sorted(required - set(columns))}.")
    if len(set(columns)) != len(columns):
        raise NsightError("Nsight returned duplicate CSV columns.")
    rows = []
    text_columns = {
        "Name",
        "Operation",
        "Kernel Name",
        "Device",
        "SrcMemKd",
        "DstMemKd",
        "Range",
        "Style",
        "NameTree",
        "RangeStack",
        "Category",
        "API Name",
        "API Function",
        "NVTX Range",
        "GridXYZ",
        "BlockXYZ",
        "Thread Name",
    }
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


def run_process(
    args: list[str], *, cwd: Path, env: dict, timeout: float, input_text: str | None = None
):
    """Terminate Nsight's helper process tree as well as its launcher on timeout."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with subprocess.Popen(
        args,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        creationflags=flags,
        start_new_session=os.name != "nt",
    ) as process:
        try:
            stdout, stderr = process.communicate(input=input_text, timeout=timeout)
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


class NsightService(AnalysisMixin, CatalogMixin):
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
        self._results: dict[str, dict] = {}

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
                "optional_reports": {
                    kind: name in available for kind, name in OPTIONAL_REPORTS.items()
                },
                "cache_dir": str(self.cache.resolve()),
                "report_parameters": {
                    name: re.findall(r"[:|]([a-z][a-z-]+)", tail)
                    for name, tail in re.findall(
                        r"^\s+([a-z][a-z0-9_]+)(.*?)\s+--", report_text, re.M
                    )
                },
                "service_reports": list(CATALOG),
                "missing_service_reports": sorted(set(CATALOG) - set(available)),
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

    def _table(
        self, report_id: str, report_name: str, query: Query, options: ReportOptions | None = None
    ):
        if report_name not in CATALOG:
            raise NsightError("Report outside the fixed CUDA/NVTX allowlist.", code="OUT_OF_SCOPE")
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
        options = options or ReportOptions()
        parameters = []
        if options.annotate_nvtx:
            parameters.append("nvtx-name")
        if options.name_format != "demangled":
            parameters.append(options.name_format)
        supported = set(capabilities.get("report_parameters", {}).get(report_name, [])) & set(
            CATALOG[report_name].parameters
        )
        if not set(parameters).issubset(supported):
            raise NsightError(
                f"Unsupported report parameters for {report_name}: {parameters}.",
                code="CAPABILITY_UNAVAILABLE",
            )
        selector = report_name + "".join(":" + value for value in parameters)
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
            selector,
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
        columns, rows = parse_csv(stdout, set(CATALOG[report_name].required))
        return columns, rows, capabilities, args

    def query(self, report_id: str, kind: str, query: Query | None = None) -> dict:
        with self._lock:
            return self._remember(self._query_result(report_id, kind, query))

    def _query_result(
        self,
        report_id: str,
        kind: str,
        query: Query | None = None,
        *,
        paginate: bool = True,
        options: ReportOptions | None = None,
    ) -> dict:
        if kind not in ALL_REPORTS and kind not in CATALOG:
            raise NsightError("Unsupported analysis kind.")
        query = query or (NvtxTraceQuery() if kind == "nvtx_trace" else Query())
        with self._lock:
            report_name = ALL_REPORTS.get(kind, kind)
            entry = CATALOG[report_name]
            columns, rows, capabilities, args = self._table(report_id, report_name, query, options)
            if kind == "kernel_trace":
                if "GrdX" not in columns:
                    raise NsightError(
                        "Unsupported trace schema: missing GrdX kernel discriminator."
                    )
                rows = [row for row in rows if row["GrdX"] is not None]
            if query.name_contains is not None:
                rows = [
                    row
                    for row in rows
                    if any(
                        query.name_contains.casefold() in str(row[column] or "").casefold()
                        for column in entry.name_columns
                    )
                ]
            defaults = {
                "kernel_trace": "Duration (ns)",
                "memory_size": "Total (B)",
                "nvtx_trace": "Start (ns)",
            }
            sort_by = query.sort_by or defaults.get(kind, entry.sort_by)
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
            page = rows[query.offset : query.offset + query.limit] if paginate else rows
            if report_name == "nvtx_pushpop_trace":
                for row in page:
                    start, end = row["Start (ns)"], row["End (ns)"]
                    row["time_query"] = (
                        {"start_ns": start, "end_ns": end}
                        if isinstance(start, int) and isinstance(end, int) and start <= end
                        else None
                    )
            next_offset = query.offset + len(page) if paginate else total
            source = self.reports[report_id]
            return {
                "report_id": report_id,
                "source": {
                    "path": str(source.path),
                    "size_bytes": source.size,
                    "mtime_ns": source.mtime_ns,
                },
                "nsight_version": capabilities["version"],
                "official_report": report_name,
                "report_options": (options or ReportOptions()).model_dump(),
                "filters": query.model_dump(exclude={"offset", "limit"} if not paginate else set()),
                "sort_by": sort_by,
                "columns": columns,
                "units": {"time": "ns", "memory": "B", "throughput": "B/s", "ratio": "%"},
                "rows": page,
                "total_rows": total,
                "offset": query.offset if paginate else 0,
                "next_offset": next_offset if next_offset < total else None,
                "provenance": {"executable": capabilities["nsys_path"], "arguments": args},
                "semantics": [
                    "Nsight includes events overlapping the selected range; event durations are not clipped.",
                    "Time (%) retains Nsight's denominator before name filtering and pagination.",
                    "Kernel cumulative time is neither application wall time nor GPU utilization.",
                    "CUDA API durations measure CPU calls, not GPU kernel execution.",
                    "No matching rows does not prove zero activity outside the recorded data.",
                ]
                + (
                    [
                        "NVTX durations measure CPU annotation ranges, not GPU completion or utilization.",
                        "Official domain-prefixed names are preserved; do not treat RangeId as an NVTX filter instance index.",
                        "NVTX trace supports Push/Pop only. Start/End ranges are available in summary only.",
                        "A returned time_query selects overlapping events across threads/devices, not launch attribution.",
                    ]
                    if report_name
                    in ("nvtx_sum", "nvtx_pushpop_sum", "nvtx_startend_sum", "nvtx_pushpop_trace")
                    else []
                )
                + list(entry.semantics),
            }

    def memory_summary(
        self, report_id: str, metric: Literal["time", "size"], query: Query | None = None
    ):
        if metric not in ("time", "size"):
            raise NsightError("metric must be 'time' or 'size'.")
        return self.query(report_id, f"memory_{metric}", query)
