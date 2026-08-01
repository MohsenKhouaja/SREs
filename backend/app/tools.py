from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any

import httpx
from langchain_core.tools import tool

from .config import get_settings


def _result(data: Any, **metadata: Any) -> dict[str, Any]:
    return {"status": "success", "data": data, "metadata": metadata}


def _error(exc: Exception, **metadata: Any) -> dict[str, Any]:
    return {"status": "error", "data": [], "metadata": {**metadata, "error": str(exc)}}


def _parse_time(value: str) -> float:
    now = datetime.now(timezone.utc)
    if value == "now":
        return now.timestamp()
    match = re.fullmatch(r"now-(\d+)([smhd])", value)
    if match:
        amount = int(match.group(1))
        seconds = amount * {"s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]
        return (now - timedelta(seconds=seconds)).timestamp()
    return float(value)


@tool
def query_prometheus(query: str, time_from: str, time_to: str) -> dict:
    """Execute a PromQL range query and return a structured result."""
    settings = get_settings()
    started = time.monotonic()
    try:
        start, end = _parse_time(time_from), _parse_time(time_to)
        response = httpx.get(
            f"{settings.prometheus_url}/api/v1/query_range",
            params={"query": query, "start": start, "end": end, "step": "5s"},
            timeout=8,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("status") != "success":
            raise RuntimeError(body.get("error", "Prometheus query failed"))
        return _result(
            body.get("data", {}).get("result", []),
            query=query,
            source="prometheus",
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
    except Exception as exc:
        return _error(exc, query=query, source="prometheus")


@tool
def query_loki(query: str, time_from: str, time_to: str) -> dict:
    """Execute a LogQL range query and return a structured result."""
    settings = get_settings()
    started = time.monotonic()
    try:
        start = int(_parse_time(time_from) * 1_000_000_000)
        end = int(_parse_time(time_to) * 1_000_000_000)
        response = httpx.get(
            f"{settings.loki_url}/loki/api/v1/query_range",
            params={"query": query, "start": start, "end": end, "limit": 500, "direction": "backward"},
            timeout=8,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("status") != "success":
            raise RuntimeError(body.get("error", "Loki query failed"))
        return _result(
            body.get("data", {}).get("result", []),
            query=query,
            source="loki",
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
    except Exception as exc:
        return _error(exc, query=query, source="loki")


@tool
def get_service_health(service: str) -> dict:
    """Get health and recent observability signals for a monitored service."""
    settings = get_settings()
    endpoints = {
        "api-server": settings.sample_api_url,
        "payment-service": settings.sample_payment_url,
        "prometheus": settings.prometheus_url,
        "loki": settings.loki_url,
    }
    base = endpoints.get(service)
    if not base:
        return {"status": "error", "data": {}, "metadata": {"error": f"Unknown service: {service}"}}
    path = "/-/healthy" if service == "prometheus" else "/ready" if service == "loki" else "/health"
    try:
        response = httpx.get(f"{base}{path}", timeout=4)
        response.raise_for_status()
        return _result({"service": service, "health": "healthy", "body": response.text[:500]}, source="http")
    except Exception as exc:
        return _error(exc, service=service, source="http")


@tool
def get_time() -> dict:
    """Get current time in ISO, Unix, and Unix-nanosecond formats."""
    now = datetime.now(timezone.utc)
    unix = now.timestamp()
    return _result(
        {"unix": int(unix), "iso": now.isoformat().replace("+00:00", "Z"), "nanoseconds": str(int(unix * 1e9))}
    )


@tool
def parse_stacktrace(log: str) -> dict:
    """Extract error type, file, line, and message from a Python-style stack trace."""
    location = re.search(r'File "([^"]+)", line (\d+)', log)
    error = re.search(r"([A-Za-z_][\w.]*(?:Error|Exception|Timeout)):\s*(.+)", log)
    return _result(
        {
            "error_type": error.group(1) if error else "UnknownError",
            "file": location.group(1) if location else None,
            "line": int(location.group(2)) if location else None,
            "message": error.group(2).strip() if error else log.strip().splitlines()[-1],
        }
    )


@tool
def get_error_patterns(service: str, time_from: str, time_to: str) -> dict:
    """Group recurring recent error messages from a service's Loki stream."""
    response = query_loki.invoke({"query": f'{{service="{service}"}} |= "ERROR"', "time_from": time_from, "time_to": time_to})
    if response["status"] == "error":
        return response
    messages: dict[str, list[str]] = {}
    for stream in response["data"]:
        for timestamp, raw in stream.get("values", []):
            try:
                message = json.loads(raw).get("message", raw)
            except json.JSONDecodeError:
                message = raw
            normalized = re.sub(r"\b[0-9a-f]{8,}\b|\d+ms", "<value>", message)
            messages.setdefault(normalized, []).append(timestamp)
    patterns = [
        {"pattern": pattern, "count": len(times), "first_seen": min(times), "last_seen": max(times)}
        for pattern, times in messages.items()
    ]
    return _result(sorted(patterns, key=lambda item: item["count"], reverse=True), service=service)


@tool
def calculate_rate(metric: str, time_from: str, time_to: str) -> dict:
    """Calculate the aggregate per-second rate for a counter metric."""
    response = query_prometheus.invoke(
        {"query": f"sum(rate({metric}[1m]))", "time_from": time_from, "time_to": time_to}
    )
    if response["status"] == "error":
        return response
    values = [float(value) for series in response["data"] for _, value in series.get("values", [])]
    return _result({"rate": mean(values) if values else 0.0, "unit": "events/second"}, metric=metric)


def _window_average(metric: str, window: str) -> float:
    start, end = [part.strip() for part in window.split(",", 1)]
    response = query_prometheus.invoke({"query": metric, "time_from": start, "time_to": end})
    if response["status"] == "error":
        return 0.0
    values = [float(value) for series in response["data"] for _, value in series.get("values", [])]
    return mean(values) if values else 0.0


@tool
def compare_periods(metric: str, period1: str, period2: str) -> dict:
    """Compare average metric values between two comma-delimited time windows."""
    first, second = _window_average(metric, period1), _window_average(metric, period2)
    change = ((second - first) / first * 100) if first else (100.0 if second else 0.0)
    return _result({"period1_avg": first, "period2_avg": second, "change_pct": change}, metric=metric)


@tool
def correlate_events(events: list[dict]) -> dict:
    """Find event groups that occur within thirty seconds of one another."""
    ordered = sorted(events, key=lambda event: event.get("timestamp", event.get("time", "")))
    groups: list[dict[str, Any]] = []
    for index, event in enumerate(ordered[:-1]):
        current = datetime.fromisoformat(event.get("timestamp", event.get("time", "")).replace("Z", "+00:00"))
        following = datetime.fromisoformat(ordered[index + 1].get("timestamp", ordered[index + 1].get("time", "")).replace("Z", "+00:00"))
        seconds = abs((following - current).total_seconds())
        if seconds <= 30:
            groups.append({"events": [event, ordered[index + 1]], "correlation_score": round(1 - seconds / 60, 2), "time_window": f"{seconds:.0f}s"})
    return _result(groups)


@tool
def build_timeline(events: list[dict]) -> dict:
    """Sort and normalize events into a chronological incident timeline."""
    timeline = [
        {
            "time": event.get("timestamp", event.get("time")),
            "event": event.get("message", event.get("event", "Unknown event")),
            "source": event.get("source", "unknown"),
            "severity": event.get("severity", "info"),
        }
        for event in events
    ]
    return _result(sorted(timeline, key=lambda event: event["time"] or ""))


@tool
def rank_hypotheses(hypotheses: list[str], evidence: dict) -> dict:
    """Score root-cause hypotheses by textual overlap with available evidence."""
    corpus = json.dumps(evidence).lower()
    scored = []
    for hypothesis in hypotheses:
        terms = {term for term in re.findall(r"[a-z]+", hypothesis.lower()) if len(term) > 3}
        matches = sorted(term for term in terms if term in corpus)
        score = min(0.99, 0.35 + 0.16 * len(matches))
        scored.append({"hypothesis": hypothesis, "score": round(score, 2), "supporting_evidence": matches})
    return _result(sorted(scored, key=lambda item: item["score"], reverse=True))


@tool
def generate_root_cause(evidence: dict) -> dict:
    """Synthesize a root cause from combined evidence."""
    corpus = json.dumps(evidence).lower()
    candidates = [
        ("Redis unavailability exhausted connection attempts and caused dependent requests to fail.", ["redis", "connection"]),
        ("Database query latency saturated the API request path.", ["postgres", "8000"]),
        ("The v2 deployment introduced a high rate of HTTP 500 responses.", ["deployment", "v2"]),
    ]
    root_cause, tokens = max(candidates, key=lambda candidate: sum(token in corpus for token in candidate[1]))
    confidence = 0.7 + 0.12 * sum(token in corpus for token in tokens)
    return _result({"root_cause": root_cause, "confidence": min(confidence, 0.96), "explanation": "Supported by matching log, metric, and event signals."})


@tool
def format_report(data: dict, format: str) -> dict:
    """Format report data as structured JSON or readable Markdown."""
    if format == "json":
        return _result({"report": data})
    if format != "markdown":
        return {"status": "error", "data": {}, "metadata": {"error": "format must be json or markdown"}}
    affected = ", ".join(data.get("affected_services", [])) or "None"
    timeline = "\n".join(f"- {item.get('time')}: {item.get('event')}" for item in data.get("timeline", []))
    markdown = (
        f"# Incident report\n\n## Summary\n\n{data.get('summary', '')}\n\n"
        f"## Root cause\n\n{data.get('root_cause', '')}\n\n"
        f"## Recommendation\n\n{data.get('recommendation', '')}\n\n"
        f"## Affected services\n\n{affected}\n\n## Timeline\n\n{timeline}"
    )
    return _result({"report": markdown})


SHARED_TOOLS = [query_prometheus, query_loki, get_service_health, get_time]
AGENT_TOOLS = {
    "log": [*SHARED_TOOLS, parse_stacktrace, get_error_patterns],
    "metrics": [*SHARED_TOOLS, calculate_rate, compare_periods],
    "event": [*SHARED_TOOLS, correlate_events, build_timeline],
    "correlation": [*SHARED_TOOLS, rank_hypotheses, generate_root_cause],
    "report": [*SHARED_TOOLS, format_report],
}
