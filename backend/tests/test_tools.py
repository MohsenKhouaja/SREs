from backend.app.tools import (
    build_timeline,
    correlate_events,
    format_report,
    get_time,
    parse_stacktrace,
    rank_hypotheses,
)


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
    assert correlate_events.invoke({"events": events})["data"][0]["correlation_score"] > 0.5
    timeline = build_timeline.invoke({"events": events})["data"]
    assert [item["event"] for item in timeline] == ["deploy", "errors"]


def test_hypothesis_ranking_and_report_formatting():
    ranking = rank_hypotheses.invoke(
        {"hypotheses": ["Redis connection failure", "Database overload"], "evidence": {"log": "Redis connection timeout"}}
    )["data"]
    assert ranking[0]["hypothesis"] == "Redis connection failure"
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
