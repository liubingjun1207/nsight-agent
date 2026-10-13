"""Bounded access to six NVIDIA expert-system rules; no custom scripts or SQL."""

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RuleName = Literal[
    "cuda_api_sync",
    "cuda_memcpy_async",
    "cuda_memcpy_sync",
    "cuda_memset_sync",
    "gpu_gaps",
    "gpu_time_util",
]


@dataclass(frozen=True)
class RuleSpec:
    purpose: str
    columns: tuple[str, ...]
    semantics: tuple[str, ...]


GPU_COLUMNS = ("Duration (ns)", "Start (ns)", "PID", "Device ID", "Context ID")
RULES = {
    "cuda_api_sync": RuleSpec(
        "Host-blocking CUDA device/stream synchronization calls",
        ("Duration (ns)", "Start (ns)", "PID", "TID", "API Name"),
        ("Duration measures the CPU synchronization API call, not GPU kernel execution.",),
    ),
    "cuda_memcpy_async": RuleSpec(
        "Asynchronous CUDA copies involving pageable memory",
        (*GPU_COLUMNS, "Src Kind", "Dst Kind", "Bytes (B)", "Stream ID", "API Name"),
        (
            "Duration measures the GPU copy, not CPU API blocking time; pageable memory is a diagnostic pattern.",
        ),
    ),
    "cuda_memcpy_sync": RuleSpec(
        "CUDA copies selected by NVIDIA's synchronous-copy rule",
        (*GPU_COLUMNS, "Src Kind", "Dst Kind", "Bytes (B)", "Stream ID", "API Name"),
        (
            "Duration measures the GPU copy. Rule membership does not by itself prove an application bottleneck.",
        ),
    ),
    "cuda_memset_sync": RuleSpec(
        "Synchronous CUDA memset patterns selected by the official rule",
        (*GPU_COLUMNS, "Memory Kind", "Bytes (B)", "Stream ID", "API Name"),
        (
            "Duration measures the GPU memset. Only patterns selected by the official rule are returned.",
        ),
    ),
    "gpu_gaps": RuleSpec(
        "GPU gaps longer than a configurable millisecond threshold",
        ("Row#", *GPU_COLUMNS),
        (
            "Gaps are computed per process/device between the first and last recorded GPU operation.",
            "Initial/final inactivity and non-actionable profiling overhead are excluded; this is not system-wide idle time.",
        ),
    ),
    "gpu_time_util": RuleSpec(
        "Low GPU time utilization in configurable chunks",
        ("Row#", "In-Use (%)", *GPU_COLUMNS),
        (
            "In-Use is GPU operation time utilization, not SM, Tensor Core, occupancy or bandwidth utilization.",
            "Concurrent operations are added and may exceed 100%; profiling overhead is included.",
            "Each process/device's first-to-last GPU operation span is divided into chunks; consecutive low chunks are coalesced.",
        ),
    ),
}


class DiagnosticOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gap_ms: int | None = Field(default=None, ge=0, le=60000)
    threshold_percent: int | None = Field(default=None, ge=0, le=100)
    chunks: int | None = Field(default=None, ge=1, le=1000)


def diagnostic_csv(stdout: str, local: Path, rule: str) -> str:
    """Remove only NVIDIA's known progress line; preserve missing-data diagnostics.

    analyze --quiet hides SKIPPED as well as no-results in 2025.6. Never use it here.
    """
    from .core import NsightError

    progress = (
        r"^Processing \["
        + re.escape(str(local))
        + r"\] with \[[^\r\n]*[\\/]"
        + re.escape(rule)
        + r"\.py\](?:\([^\r\n]*\))?\.\.\. *\r?\n"
    )
    body = re.sub(progress, "", stdout, count=1)
    if re.search(r"(?im)^\s*SKIPPED:", body):
        raise NsightError(
            f"Nsight skipped the diagnostic rule: {body.strip()[-3000:]}",
            code="MISSING_DATA",
            recovery="Collect the CUDA/NVTX events required by this rule and check scope filters; missing data is not no findings.",
        )
    if re.search(r"(?im)^\s*(?:ERROR|FATAL):", body):
        raise NsightError(
            f"Nsight diagnostic failed: {body.strip()[-3000:]}", code="COMMAND_FAILED"
        )
    return body


class DiagnosticsMixin:
    def analysis_rules(self):
        """Discover installed support without expanding the fixed rule allowlist."""
        from .core import discover_nsys

        with self._lock, self._cache_io():
            self._warnings = []
            self.cache.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="rules-", dir=self.cache) as directory:
                cwd = Path(directory)
                version = self._run(["--version"], cwd).strip()
                help_text = self._run(["analyze", "--help"], cwd)
                rule_text = self._run(["analyze", "--help-rules"], cwd)
                available = set(re.findall(r"^\s+([a-z][a-z0-9_]+)(?:\[|\s+--)", rule_text, re.M))
                parameters = {}
                for rule in RULES:
                    if rule not in available:
                        continue
                    detail = self._run(["analyze", "--help-rules", rule], cwd)
                    parameters[rule] = sorted(set(re.findall(r"^\s+([a-z]+)=", detail, re.M)))
            options = sorted(set(re.findall(r"--[a-z][a-z-]+", help_text)))
            self._analysis_capabilities = {
                "version": version,
                "nsys_path": str(discover_nsys(self.explicit_nsys)),
                "options": options,
                "rule_parameters": parameters,
                "rules": [
                    {
                        "rule": rule,
                        "available": rule in available,
                        "purpose": entry.purpose,
                        "semantics": list(entry.semantics),
                        "defaults": self._diagnostic_parameters(rule, DiagnosticOptions()),
                        "parameters": parameters.get(rule, []),
                    }
                    for rule, entry in RULES.items()
                ],
                "supported_rule_count": len(RULES),
                "warnings": list(self._warnings),
                "note": "Rule support does not establish capture data availability. Findings are candidates, not proven root causes.",
            }
            return dict(self._analysis_capabilities)

    @staticmethod
    def _diagnostic_parameters(rule, options):
        from .core import NsightError

        if options.gap_ms is not None and rule != "gpu_gaps":
            raise NsightError("gap_ms is only supported by gpu_gaps.", code="INVALID_QUERY")
        if (
            options.threshold_percent is not None or options.chunks is not None
        ) and rule != "gpu_time_util":
            raise NsightError(
                "threshold_percent/chunks are only supported by gpu_time_util.",
                code="INVALID_QUERY",
            )
        parameters = {"rows": -1}
        if rule == "gpu_gaps":
            parameters["gap"] = 500 if options.gap_ms is None else options.gap_ms
        if rule == "gpu_time_util":
            parameters["threshold"] = (
                50 if options.threshold_percent is None else options.threshold_percent
            )
            parameters["chunks"] = 30 if options.chunks is None else options.chunks
        return parameters

    def analyze(self, report_id, rule, query=None, options=None):
        from .core import NsightError, Query, parse_csv, time_argument

        if rule not in RULES:
            raise NsightError(
                "Rule outside the fixed official diagnostic allowlist.", code="OUT_OF_SCOPE"
            )
        query, options = query or Query(), options or DiagnosticOptions()
        parameters = self._diagnostic_parameters(rule, options)
        entry = RULES[rule]
        if query.name_contains is not None and "API Name" not in entry.columns:
            raise NsightError("This rule has no API name to filter.", code="INVALID_QUERY")
        sort_by = query.sort_by or "Duration (ns)"
        if sort_by not in entry.columns:
            raise NsightError(
                f"Unknown sort column {sort_by!r}. Available columns: {entry.columns}",
                code="INVALID_QUERY",
            )
        with self._lock, self._cache_io():
            capabilities = self._analysis_capabilities or self.analysis_rules()
            supported = next(r for r in capabilities["rules"] if r["rule"] == rule)
            required = {"--rule", "--format", "--output"}
            if query.nvtx is not None:
                required.add("--filter-nvtx")
            elif query.start_ns is not None or query.end_ns is not None:
                required.add("--filter-time")
            missing = required - set(capabilities["options"])
            missing_parameters = set(parameters) - set(
                capabilities["rule_parameters"].get(rule, [])
            )
            if not supported["available"] or missing or missing_parameters:
                raise NsightError(
                    f"Installed Nsight lacks {rule} support, options {sorted(missing)} or parameters {sorted(missing_parameters)}.",
                    code="CAPABILITY_UNAVAILABLE",
                    recovery="Use nsight_analysis_rules to inspect this installation; install a compatible Nsight Systems version.",
                )
            self._warnings = []
            local = self._report_input(report_id)
            selector = rule + "".join(f":{key}={value}" for key, value in parameters.items())
            args = [
                "analyze",
                "--rule",
                selector,
                "--format",
                "csv:time=ns:bytes=B",
                "--output",
                "-",
            ]
            if query.nvtx is not None:
                args += [f"--filter-nvtx={query.nvtx}"]
            elif query.start_ns is not None or query.end_ns is not None:
                args += [
                    f"--filter-time={time_argument(query.start_ns)}/{time_argument(query.end_ns)}"
                ]
            args.append(str(local))
            with tempfile.TemporaryDirectory(prefix="analyze-", dir=self.cache) as directory:
                stdout = self._run(args, Path(directory))
            stdout = diagnostic_csv(stdout, local, rule)
            if stdout.strip():
                try:
                    columns, rows = parse_csv(
                        stdout, set(entry.columns), name_columns=("API Name", "Row#")
                    )
                except NsightError as exc:
                    raise NsightError(
                        f"Unsupported diagnostic CSV for {rule}: {exc}",
                        code="UNSUPPORTED_SCHEMA",
                        recovery="Check the installed Nsight version and rule schema; malformed output is not no findings.",
                    ) from exc
            else:
                columns, rows = list(entry.columns), []
            official_count = len(rows)
            if query.name_contains is not None:
                rows = [
                    r
                    for r in rows
                    if query.name_contains.casefold() in str(r["API Name"] or "").casefold()
                ]
            present = [r for r in rows if r[sort_by] is not None]
            absent = [r for r in rows if r[sort_by] is None]
            try:
                rows = sorted(present, key=lambda r: r[sort_by], reverse=query.descending) + absent
            except TypeError as exc:
                raise NsightError(
                    "Incompatible diagnostic sort values.", code="UNSUPPORTED_SCHEMA"
                ) from exc
            total = len(rows)
            page = rows[query.offset : query.offset + query.limit]
            for row in page:
                if isinstance(row["Start (ns)"], int) and isinstance(row["Duration (ns)"], int):
                    row["time_query"] = {
                        "start_ns": row["Start (ns)"],
                        "end_ns": row["Start (ns)"] + row["Duration (ns)"],
                    }
            source = self.reports[report_id]
            return self._remember(
                {
                    "report_id": report_id,
                    "source": {
                        "path": str(source.path),
                        "size_bytes": source.size,
                        "mtime_ns": source.mtime_ns,
                    },
                    "nsight_version": capabilities["version"],
                    "official_rule": rule,
                    "rule_parameters": parameters,
                    "status": "findings" if total else "no_findings",
                    "official_findings": official_count,
                    "filters": query.model_dump(),
                    "sort_by": sort_by,
                    "columns": columns,
                    "units": {"time": "ns", "memory": "B", "ratio": "%", "gap_threshold": "ms"},
                    "rows": page,
                    "total_rows": total,
                    "offset": query.offset,
                    "next_offset": query.offset + len(page)
                    if query.offset + len(page) < total
                    else None,
                    "provenance": {"executable": capabilities["nsys_path"], "arguments": args},
                    "warnings": list(self._warnings),
                    "semantics": [
                        "Findings are official diagnostic candidates, not confirmed causes or guaranteed optimization opportunities.",
                        "No findings means no rule matches under these parameters and filters, not zero activity or proof of optimal performance.",
                        "Time/NVTX filters select overlapping events; event durations may cross boundaries. A returned time_query can guide follow-up traces.",
                        "rows=-1 disables Nsight's default 50-row truncation. Service pagination follows full rule execution and does not reduce Nsight compute cost.",
                    ]
                    + list(entry.semantics),
                }
            )
