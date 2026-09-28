import json

from backend.app.tools import (
    build_timeline,
    correlate_events,
    format_report,
    get_time,
    parse_stacktrace,
    query_loki,
    compare_periods,
    calculate_rate,
)


def test_loki_query_bounds_entries_and_line_size(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": "success",
                "data": {"result": [{"stream": {"service": "api"}, "values": [[str(index), json.dumps({"message": "x" * 2000})] for index in range(50)]}]},
            }

    monkeypatch.setattr("backend.app.tools.httpx.get", lambda *args, **kwargs: Response())
    result = query_loki.invoke({"query": "{service=\"api\"}", "time_from": "now-5m", "time_to": "now"})
    values = [value for stream in result["data"] for value in stream["values"]]

    assert len(values) <= 8
    assert all(len(raw) <= 600 for _, raw in values)
    assert result["metadata"]["truncated"] is True


def test_time_returns_all_observability_formats():
    result = get_time.invoke({})
    assert result["status"] == "success"
    assert {"unix", "iso", "nanoseconds"} <= result["data"].keys()


def test_stacktrace_parser_extracts_location_and_error():
    log = 'Traceback:\n  File "/app/service.py", line 42, in run\nConnectionError: Redis refused'
    data = parse_stacktrace.invoke({"log": log})["data"]
    assert data == {
        "error_type": "ConnectionError",
        "file": "/app/service.py",
        "line": 42,
        "message": "Redis refused",
    }


def test_event_tools_correlate_and_sort():
    events = [
        {"timestamp": "2026-08-20T10:00:20Z", "message": "errors", "source": "api"},
        {"timestamp": "2026-08-20T10:00:00Z", "message": "deploy", "source": "deploy"},
    ]
    assert correlate_events.invoke({"events": events})["data"][0]["separation_seconds"] == 20
    timeline = build_timeline.invoke({"events": events})["data"]
    assert [item["event"] for item in timeline] == ["deploy", "errors"]


def test_report_formatting():
    report = {
        "summary": "Redis failed.",
        "root_cause": "No Redis connection.",
        "recommendation": "Restore Redis.",
        "affected_services": ["api-server"],
        "timeline": [{"time": "10:00", "event": "Failure"}],
    }
    markdown = format_report.invoke({"data": report, "format": "markdown"})["data"]["report"]
    assert "# Incident report" in markdown
    assert "No Redis connection" in markdown


def test_missing_or_failed_metrics_never_become_zero_measurements(monkeypatch):
    for response in ({"status": "error", "metadata": {"error": "offline"}}, {"status": "success", "data": []}):
        class PrometheusDouble:
            @staticmethod
            def invoke(args):
                return response
        monkeypatch.setattr("backend.app.tools.query_prometheus", PrometheusDouble())
        assert compare_periods.invoke({"metric": "requests", "period1": "now-2m,now-1m", "period2": "now-1m,now"})["status"] == "error"
        assert calculate_rate.invoke({"metric": "requests", "time_from": "now-1m", "time_to": "now"})["status"] == "error"
