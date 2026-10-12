import csv
import io
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from nsight_agent.catalog import CATALOG, ReportOptions
from nsight_agent.core import NsightError, NsightService, StatsQuery
from nsight_agent.health import TOOLS, check_connection

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/official_2025.6.3.json").read_text(encoding="utf-8")
)


@pytest.fixture
def service(tmp_path, monkeypatch):
    source = tmp_path / "中文.sqlite"
    source.write_bytes(b"mock report")
    svc = NsightService(cache_dir=tmp_path / "cache")
    svc._capabilities = {
        "version": "2025.6.3",
        "reports": list(CATALOG),
        "nsys_path": "nsys",
        "options": [
            "--report",
            "--format",
            "--output",
            "--quiet",
            "--filter-time",
            "--filter-nvtx",
        ],
        "report_parameters": {name: list(spec.parameters) for name, spec in CATALOG.items()},
    }
    svc.test_id = svc.open_report(str(source))["report_id"]

    def run(args, cwd):
        name = args[2].split(":")[0]
        sample = FIXTURES[name]
        if not sample["columns"]:
            return ""
        stream = io.StringIO()
        writer = csv.DictWriter(stream, sample["columns"])
        writer.writeheader()
        writer.writerow(sample["first"])
        return stream.getvalue()

    monkeypatch.setattr(svc, "_run", run)
    return svc


@pytest.mark.parametrize("name", list(CATALOG))
def test_all_official_schemas_and_defaults(service, name):
    if not FIXTURES[name]["columns"]:
        with pytest.raises(NsightError) as error:
            service.stats(service.test_id, name)
        assert error.value.code == "MISSING_DATA"
        return
    result = service.stats(service.test_id, name, StatsQuery(limit=1))
    assert result["columns"] == FIXTURES[name]["columns"]
    assert result["sort_by"] == CATALOG[name].sort_by
    assert result["filters"]["descending"] == CATALOG[name].descending
    for column in CATALOG[name].name_columns:
        assert result["rows"][0][column] == (FIXTURES[name]["first"][column] or None)


@pytest.mark.parametrize("name", list(CATALOG))
def test_parameter_allowlist_and_forwarding(service, name):
    options = ReportOptions(name_format="base", annotate_nvtx=True)
    if not {"base", "nvtx-name"}.issubset(CATALOG[name].parameters):
        with pytest.raises(NsightError) as error:
            service.stats(service.test_id, name, options=options)
        assert error.value.code == "CAPABILITY_UNAVAILABLE"
    else:
        result = service.stats(
            service.test_id, name, StatsQuery(start_ns=0, end_ns=10_000_000_000), options
        )
        assert result["provenance"]["arguments"][2] == name + ":nvtx-name:base"
        assert "--filter-time=0.000000000s/10.000000000s" in result["provenance"]["arguments"]


def test_launch_and_projection_semantics(service):
    launched = service.stats(service.test_id, "cuda_kern_exec_trace")
    assert launched["rows"][0]["Queue Dur (ns)"] is None
    assert any("not a measured zero" in value for value in launched["semantics"])
    projected = service.stats(service.test_id, "nvtx_gpu_proj_trace")
    assert projected["rows"][0]["Projected Duration (ns)"] == 14970980009
    assert any("not summed GPU activity" in value for value in projected["semantics"])


def test_capabilities_do_not_expand_and_detect_version_limit(service):
    service._capabilities["reports"].remove("cuda_api_trace")
    service._capabilities["reports"].append("custom_script")
    result = service.capabilities()
    assert result["supported_report_count"] == 18
    assert len(result["reports"]) == 18
    assert not next(r for r in result["reports"] if r["report"] == "cuda_api_trace")["available"]
    with pytest.raises(NsightError) as error:
        service.stats(service.test_id, "cuda_api_trace")
    assert error.value.code == "CAPABILITY_UNAVAILABLE"
    with pytest.raises(NsightError) as error:
        service.stats(service.test_id, "custom_script")
    assert error.value.code == "OUT_OF_SCOPE"


def test_text_names_filter_both_kernel_and_range(service):
    result = service.stats(
        service.test_id, "nvtx_kern_sum", StatsQuery(name_contains="reduce_kernel")
    )
    assert result["rows"]
    assert (
        service.stats(service.test_id, "nvtx_kern_sum", StatsQuery(name_contains="no match"))[
            "rows"
        ]
        == []
    )
    grouped = service.stats(service.test_id, "cuda_gpu_kern_gb_sum")
    assert isinstance(grouped["rows"][0]["GridXYZ"], str)


@pytest.mark.parametrize("kwargs", [{"name_format": "custom"}, {"script": "x"}])
def test_report_options_reject_arbitrary_extensions(kwargs):
    with pytest.raises(ValidationError):
        ReportOptions(**kwargs)


def test_connection_checker_detects_hidden_or_disabled_tools(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('[mcp_servers.nsight]\ncommand="python"\nenabled=false\n')
    assert check_connection(config_path=config)["code"] == "MCP_NOT_ENABLED"
    config.write_text('[mcp_servers.nsight]\ncommand="python"\ndisabled_tools=["nsight_stats"]\n')
    assert check_connection(config_path=config)["code"] == "TOOLS_DISABLED"
    assert len(TOOLS) == 12


def test_runtime_missing_command_is_diagnostic():
    from nsight_agent.health import run_probe

    result = run_probe("nonexistent-nsight-python-command", [], timeout=1)
    assert result["code"] == "MCP_CONNECTION_FAILED"
