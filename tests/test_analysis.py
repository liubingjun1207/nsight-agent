import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from nsight_agent.analysis import CompareQuery, Scope
from nsight_agent.core import (
    ALL_REPORTS,
    NsightError,
    NsightService,
    NvtxTraceQuery,
    Query,
    parse_csv,
)


@pytest.fixture
def service(tmp_path, monkeypatch):
    svc = NsightService(cache_dir=tmp_path / "cache")
    svc._capabilities = {
        "version": "2025.6.3",
        "reports": list(ALL_REPORTS.values()),
        "nsys_path": "nsys",
        "options": [
            "--report",
            "--format",
            "--output",
            "--quiet",
            "--filter-time",
            "--filter-nvtx",
        ],
    }
    for side in ("baseline", "candidate"):
        path = tmp_path / (side + ".sqlite")
        path.write_text(side)
        setattr(svc, side, svc.open_report(str(path))["report_id"])

    def run(args, cwd):
        if "nvtx_sum" in args:
            return (
                "Total Time (ns),Instances,Style,Range\n100,2,PushPop,123\n20,1,StartEnd,:async\n"
            )
        if "nvtx_pushpop_trace" in args:
            return "Name,Start (ns),End (ns),Duration (ns),PID,TID,RangeId,ParentId,Lvl\n:step,30,50,20,1,2,9,,0\n:step,10,20,10,1,3,8,7,1\n"
        side = Path(args[-1]).read_text()
        rows = (
            "slow,100,2,50\nzero,0,1,0\nremoved,50,1,50\n"
            if side == "baseline"
            else "slow,200,4,50\nzero,10,1,10\nadded,300,2,150\n"
        )
        return "Name,Total Time (ns),Instances,Avg (ns)\n" + rows

    monkeypatch.setattr(svc, "_run", run)
    return svc


def test_nvtx_discovery_and_roundtrip_window(service):
    summary = service.query(service.baseline, "nvtx_summary")
    assert summary["rows"][0]["Range"] == "123"
    assert summary["rows"][1]["Style"] == "StartEnd"
    trace = service.query(service.baseline, "nvtx_trace", NvtxTraceQuery(name_contains="step"))
    assert [r["Start (ns)"] for r in trace["rows"]] == [10, 30]
    assert trace["rows"][0]["TID"] == 3
    assert trace["rows"][0]["ParentId"] == 7
    selected = service.query(
        service.baseline, "kernel_summary", Query(**trace["rows"][0]["time_query"])
    )
    assert "--filter-time=0.000000010s/0.000000020s" in selected["provenance"]["arguments"]
    page = service.query(service.baseline, "nvtx_trace", NvtxTraceQuery(offset=1, limit=1))
    assert page["rows"][0]["RangeId"] == 9 and page["next_offset"] is None


def test_optional_nvtx_unavailable_leaves_old_tools_working(service):
    service._capabilities["reports"].remove("nvtx_sum")
    with pytest.raises(NsightError, match="does not support"):
        service.query(service.baseline, "nvtx_summary")
    assert service.query(service.baseline, "kernel_summary")["rows"]


def test_missing_nvtx_schema_and_empty_table(service, monkeypatch):
    monkeypatch.setattr(service, "_run", lambda *a: "Range,Instances\n:step,1\n")
    with pytest.raises(NsightError, match="Unsupported report schema"):
        service.query(service.baseline, "nvtx_summary")
    monkeypatch.setattr(service, "_run", lambda *a: "Range,Style,Total Time (ns),Instances\n")
    assert service.query(service.baseline, "nvtx_summary")["rows"] == []


def test_comparison_values_missing_and_zero(service):
    result = service.compare(service.baseline, service.candidate)
    rows = {r["name"]: r for r in result["rows"]}
    assert result["rows"][0]["name"] == "slow"
    assert rows["slow"]["changes"]["Total Time (ns)"] == {
        "absolute": 100,
        "relative_percent": 100,
        "reason": None,
    }
    assert rows["slow"]["count_changed"]
    assert rows["slow"]["changes"]["Avg (ns)"]["absolute"] == 0
    assert rows["zero"]["changes"]["Total Time (ns)"]["reason"] == "zero_baseline"
    assert rows["added"]["baseline"] is None
    assert rows["removed"]["candidate"] is None
    assert rows["added"]["changes"]["Total Time (ns)"]["absolute"] is None
    assert result["status_counts"] == {"matched": 2, "added": 1, "removed": 1}
    assert result["count_changed_rows"] == 1


def test_same_report_zero_and_independent_ranges(service):
    result = service.compare(
        service.baseline,
        service.baseline,
        baseline_scope=Scope(nvtx="step/0"),
        candidate_scope=Scope(start_ns=10, end_ns=20),
    )
    assert all(r["changes"]["Total Time (ns)"]["absolute"] == 0 for r in result["rows"])
    assert "--filter-nvtx=step/0" in result["baseline"]["provenance"]["arguments"]
    assert (
        "--filter-time=0.000000010s/0.000000020s" in result["candidate"]["provenance"]["arguments"]
    )


def test_complete_tables_matched_before_page(service, monkeypatch):
    def run(args, cwd):
        candidate = Path(args[-1]).read_text() == "candidate"
        return "Name,Total Time (ns),Instances,Avg (ns)\n" + "".join(
            f"k{i},{10000 if candidate and i == 249 else 300 - i},1,1\n" for i in range(250)
        )

    monkeypatch.setattr(service, "_run", run)
    result = service.compare(service.baseline, service.candidate, query=CompareQuery(limit=1))
    assert result["total_rows"] == 250 and result["next_offset"] == 1
    assert result["rows"][0]["name"] == "k249"
    assert result["baseline"]["total_rows"] == 250
    assert result["baseline"]["next_offset"] is None
    assert "limit" not in result["baseline"]["filters"]


def test_exact_names_and_name_filter(service, monkeypatch):
    def run(args, cwd):
        name = "GEMM<float>" if Path(args[-1]).read_text() == "candidate" else "gemm<float>"
        return "Name,Total Time (ns)\n" + name + ",10\n"

    monkeypatch.setattr(service, "_run", run)
    result = service.compare(
        service.baseline, service.candidate, query=CompareQuery(name_contains="GeMm")
    )
    assert result["status_counts"] == {"matched": 0, "added": 1, "removed": 1}
    assert (
        service.compare(
            service.baseline, service.candidate, query=CompareQuery(name_contains="absent")
        )["rows"]
        == []
    )


@pytest.mark.parametrize(
    "kind,header",
    [
        ("cuda_api_summary", "Name,Total Time (ns),Num Calls,Avg (ns)"),
        ("memory_time", "Operation,Total Time (ns),Count,Avg (ns)"),
        ("memory_size", "Operation,Total (B),Count,Avg (B)"),
    ],
)
def test_api_and_memory_comparison(service, monkeypatch, kind, header):
    monkeypatch.setattr(service, "_run", lambda *a: header + "\ncopy,40,2,20\n")
    result = service.compare(service.baseline, service.candidate, kind)
    assert result["rows"][0]["changes"][result["total_metric"]]["absolute"] == 0


def test_duplicate_names_rejected(service, monkeypatch):
    monkeypatch.setattr(service, "_run", lambda *a: "Name,Total Time (ns)\nx,1\nx,2\n")
    with pytest.raises(NsightError, match="unique"):
        service.compare(service.baseline, service.candidate)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"nvtx": "step", "start_ns": 0},
        {"start_ns": 2, "end_ns": 1},
        {"limit": 2},
        {"nvtx": "a\x00b"},
    ],
)
def test_scope_validation(kwargs):
    with pytest.raises(ValidationError):
        Scope(**kwargs)


def test_exports_are_immutable_page_snapshots(service, monkeypatch):
    result = service.query(service.baseline, "kernel_summary", Query(limit=1))
    result_id = result["result_id"]
    result["rows"][0]["Name"] = "changed by caller"
    monkeypatch.setattr(service, "_run", lambda *a: pytest.fail("Export reran Nsight"))
    paths = [
        Path(service.export_analysis([result_id], f)["path"]) for f in ("json", "markdown", "json")
    ]
    assert len(set(paths)) == 3
    document = json.loads(paths[0].read_text(encoding="utf-8"))
    saved = document["results"][0]
    assert saved["rows"][0]["Name"] == "slow"
    assert saved["next_offset"] == 1 and saved["total_rows"] == 3
    md = paths[1].read_text(encoding="utf-8")
    assert "Rows shown: 1 / 3" in md
    assert json.loads(md.split("```json\n")[1].split("\n```")[0]) == saved
    assert saved["source"]["path"].endswith("baseline.sqlite")


def test_comparison_export_and_untrusted_names(service, monkeypatch):
    monkeypatch.setattr(
        service, "_run", lambda *a: 'Name,Total Time (ns)\n"中文|<script>````",10\n'
    )
    result = service.compare(service.baseline, service.candidate)
    md = Path(service.export_analysis([result["result_id"]])["path"]).read_text(encoding="utf-8")
    assert "中文&#124;&lt;script&gt;" in md
    assert "`````json" in md
    assert '"baseline"' in md and '"candidate"' in md


def test_expired_and_invalid_exports(service):
    old = service.query(service.baseline, "kernel_summary")["result_id"]
    for _ in range(100):
        service._remember({"rows": []})
    assert len(service._results) == 100
    with pytest.raises(NsightError, match="expired"):
        service.export_analysis([old])
    with pytest.raises(NsightError, match="1 to 100"):
        service.export_analysis([])
    with pytest.raises(NsightError, match="format"):
        service.export_analysis([old], "html")


def test_numeric_range_name_and_schema():
    assert parse_csv("Range,Style\n123,456\n")[1][0] == {"Range": "123", "Style": "456"}


def test_failed_candidate_does_not_save_partial_snapshot(service, monkeypatch):
    original = service._run

    def fail_candidate(args, cwd):
        if Path(args[-1]).read_text() == "candidate":
            raise NsightError("Nsight exceeded 120s")
        return original(args, cwd)

    monkeypatch.setattr(service, "_run", fail_candidate)
    with pytest.raises(NsightError, match="exceeded"):
        service.compare(service.baseline, service.candidate)
    assert service._results == {}


def test_comparison_sorts_and_out_of_range_page(service):
    result = service.compare(
        service.baseline, service.candidate, query=CompareQuery(sort_by="candidate_total")
    )
    assert result["rows"][0]["name"] == "added"
    assert result["rows"][-1]["name"] == "removed"
    result = service.compare(
        service.baseline, service.candidate, query=CompareQuery(descending=False)
    )
    assert [r["name"] for r in result["rows"][:2]] == ["zero", "slow"]
    empty = service.compare(service.baseline, service.candidate, query=CompareQuery(offset=100))
    assert empty["rows"] == [] and empty["next_offset"] is None and empty["total_rows"] == 4


def test_nvtx_missing_boundaries_not_reusable(service, monkeypatch):
    monkeypatch.setattr(
        service,
        "_run",
        lambda *a: (
            "Name,Start (ns),End (ns),Duration (ns),PID,TID,RangeId,ParentId,Lvl\n:open,5,,,1,1,2,,0\n"
        ),
    )
    assert service.query(service.baseline, "nvtx_trace")["rows"][0]["time_query"] is None


@pytest.mark.parametrize("stage", ["directory", "write"])
def test_export_cache_permission_error(service, monkeypatch, stage):
    result = service.query(service.baseline, "kernel_summary")

    def denied(*args, **kwargs):
        raise PermissionError(13, "Access is denied", str(service.cache / "exports"))

    if stage == "directory":
        monkeypatch.setattr(Path, "mkdir", denied)
    else:
        monkeypatch.setattr(Path, "open", denied)
    with pytest.raises(NsightError) as error:
        service.export_analysis([result["result_id"]])
    assert error.value.code == "CACHE_IO_ERROR"
    assert "NSIGHT_CACHE_DIR" in error.value.recovery
