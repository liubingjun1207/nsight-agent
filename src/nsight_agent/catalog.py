"""Fixed CUDA/NVTX report contract; installation discovery never expands the allowlist."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict


@dataclass(frozen=True)
class ReportSpec:
    purpose: str
    name_columns: tuple[str, ...]
    sort_by: str
    required: frozenset[str]
    descending: bool = True
    parameters: tuple[str, ...] = ()
    semantics: tuple[str, ...] = ()


def spec(purpose, names, sort, extra=(), *, trace=False, parameters=(), semantics=()):
    names = (names,) if isinstance(names, str) else names
    return ReportSpec(
        purpose, names, sort, frozenset((*names, sort, *extra)), not trace, parameters, semantics
    )


NAME_PARAMS = ("nvtx-name", "base", "mangled")
LAUNCH_SEMANTICS = (
    "API time is CPU launch-call duration; queue time is measured from API return to kernel start.",
    "A missing queue time can mean execution began before the API returned; it is not a measured zero.",
    "Total duration is not the sum of phases because they may overlap. Queueing is not inherently a bottleneck.",
)
PROJECTION_SEMANTICS = (
    "GPU projection spans the first to last GPU operation whose launch call is inside the CPU NVTX range.",
    "Projection is not summed GPU activity or utilization. Only ranges starting/ending on the same thread are included.",
)
CATALOG = {
    "cuda_api_sum": spec(
        "CPU CUDA API timing summary, including synchronization", "Name", "Total Time (ns)"
    ),
    "cuda_api_trace": spec(
        "Individual CPU CUDA API calls with correlation IDs",
        "Name",
        "Start (ns)",
        ("Duration (ns)",),
        trace=True,
    ),
    "cuda_api_gpu_sum": spec(
        "Combined CPU API/GPU kernel/memory categories; keep Category distinct",
        "Operation",
        "Total Time (ns)",
        ("Category",),
        parameters=NAME_PARAMS,
        semantics=(
            "Category separates CPU calls and GPU events; their times must not be summed into wall time.",
        ),
    ),
    "cuda_gpu_kern_sum": spec(
        "Cumulative GPU kernel duration/counts", "Name", "Total Time (ns)", parameters=NAME_PARAMS
    ),
    "cuda_gpu_kern_gb_sum": spec(
        "Kernel duration grouped by grid and block configuration",
        "Name",
        "Total Time (ns)",
        ("GridXYZ", "BlockXYZ"),
        parameters=NAME_PARAMS,
    ),
    "cuda_gpu_sum": spec(
        "GPU kernel/memcpy/memset category summary",
        "Operation",
        "Total Time (ns)",
        ("Category",),
        parameters=NAME_PARAMS,
    ),
    "cuda_gpu_trace": spec(
        "Chronological GPU kernel AND memory operations",
        "Name",
        "Start (ns)",
        ("Duration (ns)", "GrdX"),
        trace=True,
        parameters=NAME_PARAMS,
    ),
    "cuda_gpu_mem_time_sum": spec("GPU memcpy/memset timing", "Operation", "Total Time (ns)"),
    "cuda_gpu_mem_size_sum": spec("GPU memcpy/memset bytes", "Operation", "Total (B)"),
    "cuda_kern_exec_sum": spec(
        "Kernel CPU launch/queue/GPU execution summary",
        "Kernel Name",
        "TAvg (ns)",
        ("Count", "AAvg (ns)", "QAvg (ns)", "KAvg (ns)"),
        parameters=NAME_PARAMS,
        semantics=LAUNCH_SEMANTICS,
    ),
    "cuda_kern_exec_trace": spec(
        "Individual kernel CPU launch, queue and GPU execution phases",
        "Kernel Name",
        "API Start (ns)",
        (
            "API Dur (ns)",
            "Queue Dur (ns)",
            "Kernel Start (ns)",
            "Kernel Dur (ns)",
            "Total Dur (ns)",
        ),
        trace=True,
        parameters=NAME_PARAMS,
        semantics=LAUNCH_SEMANTICS,
    ),
    "nvtx_sum": spec(
        "Push/Pop and Start/End CPU NVTX range summary",
        "Range",
        "Total Time (ns)",
        ("Style", "Instances"),
    ),
    "nvtx_pushpop_sum": spec(
        "Push/Pop CPU NVTX range summary", "Range", "Total Time (ns)", ("Instances",)
    ),
    "nvtx_pushpop_trace": spec(
        "Individual Push/Pop CPU ranges with nesting and reusable windows",
        "Name",
        "Start (ns)",
        ("End (ns)", "Duration (ns)", "PID", "TID", "RangeId", "ParentId", "Lvl"),
        trace=True,
    ),
    "nvtx_startend_sum": spec(
        "Start/End CPU range summary; no individual trace support",
        "Range",
        "Total Time (ns)",
        ("Instances",),
    ),
    "nvtx_gpu_proj_sum": spec(
        "NVTX GPU projection versus original CPU range duration",
        "Range",
        "Total Proj Time (ns)",
        ("Total Range Time (ns)",),
        semantics=PROJECTION_SEMANTICS,
    ),
    "nvtx_gpu_proj_trace": spec(
        "Individual NVTX GPU projection and original CPU range timestamps",
        "Name",
        "Projected Start (ns)",
        ("Projected Duration (ns)", "Orig Start (ns)", "Orig Duration (ns)"),
        trace=True,
        semantics=PROJECTION_SEMANTICS,
    ),
    "nvtx_kern_sum": spec(
        "Kernels grouped by enclosing NVTX range and PID/TID",
        ("Kernel Name", "NVTX Range"),
        "Total Time (ns)",
        ("NVTX Inst", "Kern Inst"),
        parameters=("base", "mangled"),
        semantics=(
            "Containment uses launch calls inside same-thread/process NVTX ranges, not execution overlap.",
            "Nested ranges may associate a kernel more than once; summing these groups double-counts events.",
        ),
    ),
}

ReportName = Literal[
    "cuda_api_sum",
    "cuda_api_trace",
    "cuda_api_gpu_sum",
    "cuda_gpu_kern_sum",
    "cuda_gpu_kern_gb_sum",
    "cuda_gpu_sum",
    "cuda_gpu_trace",
    "cuda_gpu_mem_time_sum",
    "cuda_gpu_mem_size_sum",
    "cuda_kern_exec_sum",
    "cuda_kern_exec_trace",
    "nvtx_sum",
    "nvtx_pushpop_sum",
    "nvtx_pushpop_trace",
    "nvtx_startend_sum",
    "nvtx_gpu_proj_sum",
    "nvtx_gpu_proj_trace",
    "nvtx_kern_sum",
]


class ReportOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name_format: Literal["demangled", "base", "mangled"] = "demangled"
    annotate_nvtx: bool = False


class CatalogMixin:
    def capabilities(self):
        capabilities = self._capabilities or self.doctor()
        return {
            "nsight_version": capabilities["version"],
            "supported_report_count": len(CATALOG),
            "reports": [
                {
                    "report": name,
                    "purpose": entry.purpose,
                    "available": name in capabilities["reports"],
                    "name_columns": list(entry.name_columns),
                    "required_columns": sorted(entry.required),
                    "default_sort": entry.sort_by,
                    "default_descending": entry.descending,
                    "parameters": [
                        p
                        for p in entry.parameters
                        if p in capabilities.get("report_parameters", {}).get(name, [])
                    ],
                    "semantics": list(entry.semantics),
                }
                for name, entry in CATALOG.items()
            ],
            "query_options": capabilities["options"],
            "note": "Available means installed report support, not that a capture contains the required data. Use nsight_stats for any listed available report.",
        }

    def stats(self, report_id, report_name, query=None, options=None):
        from .core import NsightError, Query

        if report_name not in CATALOG:
            raise NsightError("Report outside the fixed CUDA/NVTX allowlist.", code="OUT_OF_SCOPE")
        entry = CATALOG[report_name]
        if query is None:
            query = Query(sort_by=entry.sort_by, descending=entry.descending)
        else:
            values = query.model_dump()
            if query.descending is None:
                values["descending"] = entry.descending
            query = Query(**values)
        with self._lock:
            return self._remember(
                self._query_result(report_id, report_name, query, options=options)
            )
