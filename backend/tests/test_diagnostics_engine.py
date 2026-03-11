"""Integration tests for DiagnosticsEngine end-to-end cycle."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
import pytest
from diagnostics.engine import DiagnosticsEngine
from monitoring.metrics_registry import MetricsRegistry


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset MetricsRegistry singleton between tests."""
    MetricsRegistry._instance = None
    yield
    MetricsRegistry._instance = None


class TestDiagnosticsEngine:
    def test_engine_starts_and_stops(self):
        engine = DiagnosticsEngine(poll_interval_seconds=1)
        assert not engine._running
        engine.stop()
        assert not engine._running

    def test_healthy_snapshot_produces_no_reports(self):
        engine = DiagnosticsEngine(poll_interval_seconds=1)
        # Healthy metrics → no alerts
        asyncio.run(engine._evaluate_cycle())
        assert len(engine.get_report_history()) == 0

    def test_critical_wer_produces_report(self):
        engine = DiagnosticsEngine(poll_interval_seconds=1)
        registry = MetricsRegistry.instance()
        registry.set_metric("stt_word_error_rate", 0.35)
        asyncio.run(engine._evaluate_cycle())
        reports = engine.get_report_history()
        assert len(reports) >= 1
        assert reports[-1]["pipeline_status"] in ("DEGRADED", "CRITICAL")

    def test_report_contains_rca(self):
        engine = DiagnosticsEngine(poll_interval_seconds=1)
        registry = MetricsRegistry.instance()
        registry.set_metric("stt_word_error_rate", 0.35)
        registry.set_metric("audio_snr_db", 5.0)
        asyncio.run(engine._evaluate_cycle())
        reports = engine.get_report_history()
        assert len(reports) >= 1
        report = reports[-1]
        assert "root_cause_analysis" in report
        assert report["root_cause_analysis"]["confidence"] > 0.0

    def test_active_alerts_tracked(self):
        engine = DiagnosticsEngine(poll_interval_seconds=1)
        registry = MetricsRegistry.instance()
        registry.set_metric("llm_error_rate_429", 0.50)
        asyncio.run(engine._evaluate_cycle())
        alerts = engine.get_active_alerts()
        rule_ids = [a["rule_id"] for a in alerts]
        assert "LLM_RATE_LIMIT" in rule_ids

    def test_alert_clears_when_metric_recovers(self):
        engine = DiagnosticsEngine(poll_interval_seconds=1)
        registry = MetricsRegistry.instance()
        # Fire alert
        registry.set_metric("llm_error_rate_429", 0.50)
        asyncio.run(engine._evaluate_cycle())
        assert "LLM_RATE_LIMIT" in engine._active_alerts
        # Recover
        registry.set_metric("llm_error_rate_429", 0.01)
        asyncio.run(engine._evaluate_cycle())
        assert "LLM_RATE_LIMIT" not in engine._active_alerts

    def test_broadcast_callback_called_on_alert(self):
        received = []

        async def mock_broadcast(report_dict):
            received.append(report_dict)

        engine = DiagnosticsEngine(poll_interval_seconds=1)
        engine.set_broadcast_callback(mock_broadcast)
        registry = MetricsRegistry.instance()
        registry.set_metric("stt_word_error_rate", 0.35)
        asyncio.run(engine._evaluate_cycle())
        assert len(received) >= 1
        assert "report_id" in received[0]
