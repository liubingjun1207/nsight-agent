import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from nsight_agent.compute import METRICS, ComputeQuery, discover_ncu, parse_compute_csv
from nsight_agent.core import NsightError, NsightService

METRIC = METRICS["occupancy"][0]
CSV = f'''"ID","Kernel Name","Device","{METRIC}"
"","","","%"
"0","中文 gemm<float>","0","73.53"
"1","vector_add","0","N/A"
'''


@pytest.fixture
def service(tmp_path, monkeypatch):
    svc = NsightService(cache_dir=tmp_path / "cache")
    svc._compute_capabilities = {"version": "2026.1.0", "ncu_path": "ncu", "missing_options": []}
    source = tmp_path / "中文 report.ncu-rep"
    source.write_bytes(b"fake compute report")
    svc.test_source = source
    svc.test_id = svc.compute_open_report(str(source))["report_id"]
    monkeypatch.setattr(svc, "_run_compute", lambda *a: CSV)
    return svc


def test_units_missing_metrics_and_pagination(service):
    result = service.compute_metrics(service.test_id, query=ComputeQuery(limit=1))
    assert result["rows"][0]["Metric Value"] == 73.53
    assert result["rows"][0]["Metric Unit"] == "%"
    assert result["available_metrics"] == [METRIC] and result["missing_metrics"]
    assert result["next_offset"] == 1
    missing = service.compute_metrics(service.test_id, query=ComputeQuery(offset=1))
    assert missing["rows"][0]["Metric Value"] is None
    assert missing["rows"][0]["measurement_status"] == "unavailable"
    assert missing["rows"][0]["Raw Value"] == "N/A"
    assert Path(result["provenance"]["arguments"][3]) != service.test_source


def test_compute_filters_and_export(service):
    result = service.compute_metrics(
        service.test_id, query=ComputeQuery(name_contains="中文", kernel_id="0")
    )
    assert result["total_rows"] == 1
    exported = service.export_analysis([result["result_id"]], "json")
    assert json.loads(Path(exported["path"]).read_text(encoding="utf-8"))["results"][0] == result
    assert (
        service.compute_metrics(service.test_id, query=ComputeQuery(name_contains="absent"))["rows"]
        == []
    )


def test_original_is_preserved_and_changed_source_rejected(service):
    before = service.test_source.read_bytes()
    service.compute_metrics(service.test_id)
    assert service.test_source.read_bytes() == before
    service.test_source.write_bytes(b"changed")
    with pytest.raises(NsightError) as error:
        service.compute_metrics(service.test_id)
    assert error.value.code == "REPORT_CHANGED"


def test_missing_metric_group_is_not_zero(service):
    with pytest.raises(NsightError) as error:
        service.compute_metrics(service.test_id, "memory")
    assert error.value.code == "MISSING_DATA"
    with pytest.raises(NsightError):
        service.compute_metrics("expired")
    with pytest.raises(NsightError) as error:
        service.compute_metrics(service.test_id, "arbitrary")
    assert error.value.code == "OUT_OF_SCOPE"


@pytest.mark.parametrize("text", ["", "ID,Kernel Name,Device\n0,gemm,0\n", CSV + "bad,row\n"])
def test_malformed_compute_csv(text):
    with pytest.raises(NsightError):
        parse_compute_csv(text, [METRIC])


def test_integer_precision_and_thousands():
    rows, _ = parse_compute_csv(CSV.replace('"73.53"', '"9,007,199,254,740,993"'), [METRIC])
    assert rows[0]["Metric Value"] == 9007199254740993


def test_missing_optional_compute_does_not_disable_systems(tmp_path, monkeypatch):
    monkeypatch.setenv("NSIGHT_NCU_PATH", str(tmp_path / "missing-ncu"))
    with pytest.raises(NsightError) as error:
        discover_ncu()
    assert error.value.code == "NCU_NOT_FOUND"
    report = tmp_path / "valid.sqlite"
    report.write_bytes(b"Systems still registers")
    assert NsightService().open_report(str(report))["status"] == "registered"


def test_compute_command_disables_user_config(tmp_path, monkeypatch):
    executable = tmp_path / "ncu"
    executable.touch()
    monkeypatch.setenv("NSIGHT_NCU_PATH", str(executable))
    monkeypatch.setenv("PYTHONPATH", "untrusted")

    def run(args, **kwargs):
        assert args == [str(executable), "--config-file", "off", "--version"]
        assert "PYTHONPATH" not in kwargs["env"]
        return subprocess.CompletedProcess(args, 0, "2026.1.0", "WARNING: optional feature")

    monkeypatch.setattr("nsight_agent.core.run_process", run)
    svc = NsightService()
    assert svc._run_compute(["--version"], tmp_path) == "2026.1.0"
    assert svc._warnings[0]["message"].startswith("WARNING")


@pytest.mark.parametrize("kwargs", [{"metrics": "anything"}, {"start_ns": 0}, {"limit": 201}])
def test_compute_query_has_no_arbitrary_metrics_or_time_join(kwargs):
    with pytest.raises(ValidationError):
        ComputeQuery(**kwargs)


@pytest.mark.parametrize("channel", ["stdout", "stderr"])
def test_compute_error_diagnostic_cannot_hide_behind_zero_exit(tmp_path, monkeypatch, channel):
    executable = tmp_path / "ncu"
    executable.touch()
    monkeypatch.setenv("NSIGHT_NCU_PATH", str(executable))
    diagnostic = "==ERROR== Cannot import report"
    monkeypatch.setattr(
        "nsight_agent.core.run_process",
        lambda *a, **kw: subprocess.CompletedProcess(
            [],
            0,
            diagnostic if channel == "stdout" else CSV,
            diagnostic if channel == "stderr" else "",
        ),
    )
    with pytest.raises(NsightError) as error:
        NsightService()._run_compute(["--import", "file.ncu-rep"], tmp_path)
    assert error.value.code == "COMMAND_FAILED"
