"""
DiagnosticsEngine — the core diagnostic loop.

Runs on a configurable polling interval, evaluates all rules and anomaly
detectors against the current metric snapshot, performs root cause analysis
on any fired alerts, generates a DiagnosticReport, and broadcasts it over
WebSocket to connected clients.

This is the central component that analogises to a vehicle's onboard
diagnostic controller: continuously monitoring sensors, correlating readings,
and producing structured fault reports.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from diagnostics.anomaly_detector import AnomalyDetector
from diagnostics.report_generator import DiagnosticReport, ReportGenerator
from diagnostics.root_cause_analyzer import RootCauseAnalyzer
from diagnostics.rules import RULES, RuleResult
from monitoring.metrics_registry import MetricsRegistry

logger = logging.getLogger(__name__)


class DiagnosticsEngine:
    """
    Core diagnostic loop.

    Usage (inside FastAPI lifespan):
        engine = DiagnosticsEngine(poll_interval_seconds=10)
        asyncio.create_task(engine.run())
        ...
        engine.stop()
    """

    def __init__(
        self,
        poll_interval_seconds: int = 10,
        anomaly_window: int = 300,
        zscore_threshold: float = 3.0,
    ) -> None:
        self.poll_interval = poll_interval_seconds
        self.registry = MetricsRegistry.instance()
        self.anomaly_detector = AnomalyDetector(
            window_size=anomaly_window, threshold=zscore_threshold
        )
        self.rca = RootCauseAnalyzer()
        self.report_gen = ReportGenerator()
        self._active_alerts: dict[str, RuleResult] = {}
        self._running = False
        self._broadcast_callback: Optional[asyncio.coroutines.coroutine] = None
        self._report_history: list[DiagnosticReport] = []

    def set_broadcast_callback(self, callback) -> None:  # type: ignore[type-arg]
        """Register the WebSocket broadcast coroutine."""
        self._broadcast_callback = callback

    async def run(self) -> None:
        self._running = True
        logger.info(
            "DiagnosticsEngine started",
            extra={"poll_interval_s": self.poll_interval},
        )
        while self._running:
            try:
                await self._evaluate_cycle()
            except Exception:
                logger.exception("DiagnosticsEngine cycle error")
            await asyncio.sleep(self.poll_interval)

    async def _evaluate_cycle(self) -> None:
        snapshot = self.registry.snapshot()
        fired: list[RuleResult] = []

        # ── Threshold rules ────────────────────────────────────────────
        for rule in RULES:
            result = rule.evaluate(snapshot)
            if result.triggered:
                fired.append(result)
                if rule.rule_id not in self._active_alerts:
                    logger.warning(
                        "diagnostic_alert_fired",
                        extra={
                            "rule_id": rule.rule_id,
                            "dtc_code": result.dtc_code,
                            "severity": result.severity.value,
                            "value": round(result.current_value, 4),
                        },
                    )
                self._active_alerts[rule.rule_id] = result
                self.registry.diagnostics_alert_total.labels(
                    rule_id=rule.rule_id,
                    severity=result.severity.value,
                ).inc()
            else:
                if rule.rule_id in self._active_alerts:
                    logger.info(
                        "diagnostic_alert_cleared",
                        extra={"rule_id": rule.rule_id},
                    )
                self._active_alerts.pop(rule.rule_id, None)

        # ── Statistical anomaly detection ──────────────────────────────
        anomalies = self.anomaly_detector.evaluate(snapshot)
        fired.extend(anomalies)

        if not fired:
            return

        # ── Root cause analysis ────────────────────────────────────────
        rca = self.rca.analyze(fired)

        # ── Report generation ──────────────────────────────────────────
        report = self.report_gen.build(
            alerts=fired,
            rca=rca,
            snapshot=snapshot,
        )
        self.registry.diagnostics_report_total.inc()
        self._report_history.append(report)
        if len(self._report_history) > 100:
            self._report_history.pop(0)

        logger.warning(
            "diagnostic_report_generated",
            extra={
                "report_id": report.report_id,
                "status": report.pipeline_status,
                "alert_count": len(fired),
                "rca_cause": rca.probable_cause,
                "rca_confidence": rca.confidence,
            },
        )

        # ── Broadcast ──────────────────────────────────────────────────
        if self._broadcast_callback:
            try:
                await self._broadcast_callback(report.to_dict())
            except Exception:
                logger.exception("Failed to broadcast diagnostic report")

    def stop(self) -> None:
        self._running = False
        logger.info("DiagnosticsEngine stopped")

    def get_report_history(self) -> list[dict]:
        return [r.to_dict() for r in self._report_history]

    def get_active_alerts(self) -> list[dict]:
        return [
            {
                "rule_id": a.rule_id,
                "dtc_code": a.dtc_code,
                "severity": a.severity.value,
                "message": a.message,
                "current_value": a.current_value,
            }
            for a in self._active_alerts.values()
        ]
