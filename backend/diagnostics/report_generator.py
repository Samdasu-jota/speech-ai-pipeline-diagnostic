"""
ReportGenerator — builds structured DiagnosticReport objects.

Reports follow a standardised schema analogous to technician-facing
service reports: they capture the pipeline health state, active alerts,
root cause analysis, and a metric snapshot at the time of detection.

Stage names are aligned with the Self English Tutor app's Celery pipeline:
  preprocessing  → AudioStage (VAD, noise reduction)
  transcription  → STTStage   (Whisper API)
  storage        → StorageStage (S3 + Celery queue)
  feedback       → FeedbackStage (GPT-4o)
"""

from __future__ import annotations

import uuid
from datetime import datetime, UTC
from typing import Optional

from diagnostics.rules import RuleResult, Severity
from diagnostics.root_cause_analyzer import RCAResult


# Health state thresholds
def _pipeline_status(fired: list[RuleResult]) -> str:
    if not fired:
        return "HEALTHY"
    severities = {r.severity for r in fired}
    if Severity.CRITICAL in severities:
        return "CRITICAL"
    return "DEGRADED"


_STAGE_NAMES = [
    "preprocessing",
    "transcription",
    "storage",
    "feedback",
    "system",
    "pipeline",
]

_STAGE_METRIC_RULES = {
    "preprocessing": ["LOW_AUDIO_SNR", "AUD_NEAR_SILENT"],
    "transcription": ["STT_HIGH_WER", "STT_LOW_CONFIDENCE", "STT_LOW_CONFIDENCE_SCORE", "STT_LOW_SPEECH_RATIO"],
    "storage": [],
    "feedback": ["FBK_LATENCY_SPIKE", "FBK_RATE_LIMIT", "FBK_POOR_QUALITY"],
    "system": ["HIGH_CPU", "HIGH_MEMORY"],
    "pipeline": ["PIPELINE_TIMEOUT"],
}


def _stage_health(fired: list[RuleResult]) -> dict[str, str]:
    fired_ids = {r.rule_id for r in fired}
    severity_by_stage: dict[str, Optional[Severity]] = {s: None for s in _STAGE_NAMES}

    for alert in fired:
        stage = alert.stage
        if stage not in severity_by_stage:
            continue
        current = severity_by_stage[stage]
        if current is None or (
            alert.severity == Severity.CRITICAL
            or (alert.severity == Severity.WARN and current == Severity.INFO)
        ):
            severity_by_stage[stage] = alert.severity

    # Also check stage-rule mapping for any fired rules
    for stage, rule_ids in _STAGE_METRIC_RULES.items():
        for rid in rule_ids:
            if rid in fired_ids:
                for alert in fired:
                    if alert.rule_id == rid:
                        current = severity_by_stage[stage]
                        if current is None:
                            severity_by_stage[stage] = alert.severity

    return {
        stage: (sev.value if sev else "HEALTHY")
        for stage, sev in severity_by_stage.items()
    }


class ReportGenerator:
    """Assembles a DiagnosticReport from alerts, RCA, and a metrics snapshot."""

    def build(
        self,
        alerts: list[RuleResult],
        rca: RCAResult,
        snapshot: dict[str, float],
    ) -> "DiagnosticReport":
        return DiagnosticReport(
            report_id=f"diag-{uuid.uuid4().hex[:12]}",
            timestamp=datetime.now(UTC).isoformat(),
            pipeline_status=_pipeline_status(alerts),
            active_alerts=alerts,
            root_cause_analysis=rca,
            stage_health=_stage_health(alerts),
            metrics_snapshot={
                k: round(v, 4)
                for k, v in snapshot.items()
                if k in {
                    "stt_word_error_rate",
                    "stt_confidence_score",
                    "audio_snr_db",
                    "audio_speech_ratio",
                    "feedback_api_latency_p99_ms",
                    "feedback_error_rate_429",
                    "feedback_grammar_score",
                    "feedback_overall_score",
                    "celery_queue_depth",
                    "system_cpu_percent",
                    "system_memory_percent",
                    "pipeline_e2e_latency_p99_ms",
                }
            },
        )


class DiagnosticReport:
    """
    A structured diagnostic report produced by the DiagnosticsEngine.

    This is the primary artifact consumed by the React dashboard,
    the Grafana annotations layer, and the operator log.
    """

    def __init__(
        self,
        report_id: str,
        timestamp: str,
        pipeline_status: str,
        active_alerts: list[RuleResult],
        root_cause_analysis: RCAResult,
        stage_health: dict[str, str],
        metrics_snapshot: dict[str, float],
    ) -> None:
        self.report_id = report_id
        self.timestamp = timestamp
        self.pipeline_status = pipeline_status
        self.active_alerts = active_alerts
        self.root_cause_analysis = root_cause_analysis
        self.stage_health = stage_health
        self.metrics_snapshot = metrics_snapshot

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "timestamp": self.timestamp,
            "pipeline_status": self.pipeline_status,
            "active_alerts": [
                {
                    "rule_id": a.rule_id,
                    "dtc_code": a.dtc_code,
                    "severity": a.severity.value,
                    "message": a.message,
                    "current_value": a.current_value,
                    "baseline_value": a.baseline_value,
                    "stage": a.stage,
                }
                for a in self.active_alerts
            ],
            "root_cause_analysis": {
                "probable_cause": self.root_cause_analysis.probable_cause,
                "confidence": self.root_cause_analysis.confidence,
                "evidence": self.root_cause_analysis.evidence,
                "suggested_fix": self.root_cause_analysis.suggested_fix,
                "matched_rule_id": self.root_cause_analysis.matched_rule_id,
                "affected_stages": self.root_cause_analysis.affected_stages,
            },
            "stage_health": self.stage_health,
            "metrics_snapshot": self.metrics_snapshot,
        }
