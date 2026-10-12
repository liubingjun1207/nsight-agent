"""Compare official tables and export immutable, session-local evidence snapshots."""

from __future__ import annotations

import copy
import html
import json
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Scope(BaseModel):
    """Independent range selection for one side of a comparison."""

    model_config = ConfigDict(extra="forbid")
    start_ns: int | None = None
    end_ns: int | None = None
    nvtx: str | None = Field(default=None, min_length=1, max_length=1024)

    @model_validator(mode="after")
    def validate_scope(self):
        from .core import Query

        Query(**self.model_dump())
        return self


class CompareQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name_contains: str | None = Field(default=None, max_length=1024)
    sort_by: Literal[
        "delta_total", "absolute_delta_total", "baseline_total", "candidate_total", "name"
    ] = "delta_total"
    descending: bool = True
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=200)


AnalysisKind = Literal["kernel_summary", "cuda_api_summary", "memory_time", "memory_size"]


def difference(before, after):
    if before is None or after is None:
        return {"absolute": None, "relative_percent": None, "reason": "missing_side"}
    delta = after - before
    percent = delta / before * 100 if before else None
    reason = "zero_baseline" if not before else None
    if percent is not None and not math.isfinite(percent):
        percent, reason = None, "non_finite_ratio"
    return {"absolute": delta, "relative_percent": percent, "reason": reason}


def compare_tables(baseline, candidate, kind, query):
    """Exact full-name matching; never aggregate medians or silently merge duplicates."""
    from .core import NsightError

    total = "Total (B)" if kind == "memory_size" else "Total Time (ns)"
    name_column = "Operation" if kind.startswith("memory_") else "Name"
    required = {name_column, total}
    for result in (baseline, candidate):
        if not required.issubset(result["columns"]):
            raise NsightError(f"Unsupported comparison schema: requires {sorted(required)}.")
    metrics = [c for c in baseline["columns"] if c in candidate["columns"] and c != name_column]

    def index(result):
        indexed = {}
        for row in result["rows"]:
            name = row[name_column]
            if not isinstance(name, str) or name in indexed:
                raise NsightError("Comparison requires unique, nonempty official names.")
            if not name:
                raise NsightError("Comparison requires unique, nonempty official names.")
            value = row[total]
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise NsightError(f"Comparison requires numeric {total}.")
            indexed[name] = row
        return indexed

    left, right = index(baseline), index(candidate)
    rows = []
    for name in sorted(left.keys() | right.keys()):
        if (
            query.name_contains is not None
            and query.name_contains.casefold() not in name.casefold()
        ):
            continue
        b, c = left.get(name), right.get(name)
        changes = {}
        for metric in metrics:
            bv, cv = b.get(metric) if b else None, c.get(metric) if c else None
            if all(v is None or isinstance(v, (int, float)) for v in (bv, cv)):
                changes[metric] = difference(bv, cv)
        rows.append(
            {
                "name": name,
                "status": "matched"
                if b is not None and c is not None
                else "added"
                if b is None
                else "removed",
                "baseline": b,
                "candidate": c,
                "changes": changes,
                "count_changed": bool(
                    b
                    and c
                    and any(b.get(k) != c.get(k) for k in ("Instances", "Num Calls", "Count"))
                ),
            }
        )

    def key(row):
        if query.sort_by == "name":
            return row["name"]
        if query.sort_by in ("baseline_total", "candidate_total"):
            side = row[query.sort_by.split("_")[0]]
            return side[total] if side else None
        value = row["changes"][total]["absolute"]
        return (
            abs(value) if value is not None and query.sort_by == "absolute_delta_total" else value
        )

    present = [r for r in rows if key(r) is not None]
    absent = [r for r in rows if key(r) is None]
    ordered = sorted(present, key=key, reverse=query.descending) + absent
    page = ordered[query.offset : query.offset + query.limit]
    end = query.offset + len(page)
    return {
        "kind": kind,
        "total_metric": total,
        "filters": query.model_dump(),
        "sort_by": query.sort_by,
        "rows": page,
        "total_rows": len(rows),
        "offset": query.offset,
        "next_offset": end if end < len(rows) else None,
        "status_counts": {
            status: sum(r["status"] == status for r in rows)
            for status in ("matched", "added", "removed")
        },
        "count_changed_rows": sum(r["count_changed"] for r in rows),
        "semantics": [
            "Changes are candidate minus baseline; relative_percent = change / baseline * 100.",
            "Missing sides are not measured zeros; their differences are null and sort last when sorting by deltas.",
            "Exact official names are matched across complete tables before pagination; no fuzzy matching or fusion attribution.",
            "Each Time (%) retains its own official denominator; its absolute change is in percentage points.",
            "Counts and selected workloads may differ. Cumulative-time reductions are not application speedup.",
            "Time filters include complete overlapping events and may include concurrent work on other threads/devices.",
            "CPU API time, GPU execution time, and application wall time are distinct.",
        ],
    }


def markdown_export(document):
    """Escape event text; include exact JSON evidence alongside readable tables."""

    def cell(value):
        return (
            html.escape(str(value), quote=False)
            .replace("\\", "&#92;")
            .replace("[", "&#91;")
            .replace("]", "&#93;")
            .replace("*", "&#42;")
            .replace("_", "&#95;")
            .replace("~", "&#126;")
            .replace("|", "&#124;")
            .replace("`", "&#96;")
            .replace("\n", "<br>")
            .replace("\r", "")
        )

    lines = [
        "# Nsight analysis evidence",
        "",
        f"Exported: {document['exported_at']}",
        "",
        "Selected result pages only. Check total_rows, offset and next_offset; these are not necessarily complete tables.",
        "",
    ]
    for result in document["results"]:
        lines += [
            f"## Result {result['result_id']}",
            "",
            f"Rows shown: {len(result['rows'])} / {result['total_rows']}; offset: {result['offset']}.",
            "",
        ]
        if "baseline" in result:
            metric = result["total_metric"]
            headers = [
                "Name",
                "Status",
                "Baseline " + metric,
                "Candidate " + metric,
                "Change",
                "Change (%)",
            ]
            values = [
                [
                    r["name"],
                    r["status"],
                    (r["baseline"] or {}).get(metric),
                    (r["candidate"] or {}).get(metric),
                    r["changes"][metric]["absolute"],
                    r["changes"][metric]["relative_percent"],
                ]
                for r in result["rows"]
            ]
        else:
            headers = result["columns"]
            values = [[r.get(c) for c in headers] for r in result["rows"]]
        lines += [
            "| " + " | ".join(map(cell, headers)) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in values]
        lines += [
            "",
            "Exact evidence (units, sources, filters, commands and semantics included):",
            "",
        ]
        payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
        fence = "`" * max(3, 1 + max((len(x) for x in re.findall(r"`+", payload)), default=0))
        lines += [fence + "json", payload, fence, ""]
    return "\n".join(lines)


class AnalysisMixin:
    def _remember(self, result):
        result["result_id"] = uuid.uuid4().hex
        result["recorded_at"] = datetime.now(timezone.utc).isoformat()
        # Bounded memory; IDs expire after 100 later analyses or service restart.
        self._results[result["result_id"]] = copy.deepcopy(result)
        while len(self._results) > 100:
            self._results.pop(next(iter(self._results)))
        return result

    def compare(
        self,
        baseline_report_id,
        candidate_report_id,
        kind="kernel_summary",
        baseline_scope=None,
        candidate_scope=None,
        query=None,
    ):
        from .core import NsightError, Query

        if kind not in ("kernel_summary", "cuda_api_summary", "memory_time", "memory_size"):
            raise NsightError("Unsupported comparison kind.")
        query = query or CompareQuery()
        with self._lock:
            b = self._query_result(
                baseline_report_id,
                kind,
                Query(**(baseline_scope or Scope()).model_dump()),
                paginate=False,
            )
            c = self._query_result(
                candidate_report_id,
                kind,
                Query(**(candidate_scope or Scope()).model_dump()),
                paginate=False,
            )
            result = compare_tables(b, c, kind, query)
            # Keep complete-table provenance but only the requested comparison page in model output.
            result["baseline"] = {k: v for k, v in b.items() if k != "rows"}
            result["candidate"] = {k: v for k, v in c.items() if k != "rows"}
            result["units"] = b["units"]
            return self._remember(result)

    def export_analysis(self, result_ids, format="markdown"):
        from .core import NsightError

        if format not in ("markdown", "json"):
            raise NsightError("Export format must be markdown or json.")
        if not result_ids or len(result_ids) > 100:
            raise NsightError("Select 1 to 100 result IDs.")
        with self._lock:
            if any(r not in self._results for r in result_ids):
                raise NsightError(
                    "Unknown or expired result_id; rerun the analysis (last 100 results per session retained)."
                )
            document = {
                "schema_version": "1",
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "results": [self._results[r] for r in result_ids],
            }
            content = (
                json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False)
                if format == "json"
                else markdown_export(document)
            )
            directory = self.cache / "exports"
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / (
                "analysis-" + uuid.uuid4().hex + (".json" if format == "json" else ".md")
            )
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content + "\n")
            return {
                "path": str(path.resolve()),
                "format": format,
                "result_ids": list(result_ids),
                "note": "Exports contain selected pages and local source paths/commands. No Nsight query was rerun.",
            }
