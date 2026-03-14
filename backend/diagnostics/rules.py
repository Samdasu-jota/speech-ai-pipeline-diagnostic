"""
Diagnostic rules — threshold-based fault detection with DTC-style codes.

Each Rule maps a metric name to a condition function and fires a RuleResult
when the condition is met. Rules use DTC-style IDs (e.g., STT-001) to mirror
the conventions of automotive OBD-II diagnostic trouble codes.

DTC code prefix mapping (aligned with Self English Tutor pipeline stages):
  AUD-xxx  Preprocessing stage  (audio SNR, speech ratio)
  STT-xxx  Transcription stage  (WER, Whisper confidence, word count)
  FBK-xxx  Feedback stage       (GPT-4o latency, rate limit, quality scores)
  SYS-xxx  System / infra       (CPU, memory, E2E latency)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional


class Severity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


@dataclass
class RuleResult:
    rule_id: str
    dtc_code: str          # DTC-style code e.g. "STT-001"
    triggered: bool
    severity: Severity
    message: str
    current_value: float
    baseline_value: Optional[float] = None
    stage: str = "unknown"


@dataclass
class Rule:
    rule_id: str
    dtc_code: str
    stage: str
    metric: str
    condition: Callable[[float], bool]
    severity: Severity
    message: str
    baseline: Optional[float] = None

    def evaluate(self, snapshot: dict[str, float]) -> RuleResult:
        value = snapshot.get(self.metric, 0.0)
        triggered = self.condition(value)
        return RuleResult(
            rule_id=self.rule_id,
            dtc_code=self.dtc_code,
            triggered=triggered,
            severity=self.severity,
            message=self.message,
            current_value=value,
            baseline_value=self.baseline,
            stage=self.stage,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Rule Definitions
# ──────────────────────────────────────────────────────────────────────────────

RULES: list[Rule] = [
    # ── Preprocessing (AUD) ──────────────────────────────────────────
    Rule(
        rule_id="LOW_AUDIO_SNR",
        dtc_code="AUD-001",
        stage="preprocessing",
        metric="audio_snr_db",
        condition=lambda v: v < 10.0,
        severity=Severity.WARN,
        message="Audio SNR below 10 dB — background noise degrading preprocessing quality",
        baseline=22.0,
    ),
    Rule(
        rule_id="AUD_NEAR_SILENT",
        dtc_code="AUD-002",
        stage="preprocessing",
        metric="audio_speech_ratio",
        condition=lambda v: v < 0.20,
        severity=Severity.CRITICAL,
        message="Speech ratio below 20% — audio is nearly silent, VAD detected almost no speech",
        baseline=0.82,
    ),

    # ── Transcription (STT) ──────────────────────────────────────────
    Rule(
        rule_id="STT_HIGH_WER",
        dtc_code="STT-001",
        stage="transcription",
        metric="stt_word_error_rate",
        condition=lambda v: v > 0.20,
        severity=Severity.CRITICAL,
        message="STT Word Error Rate exceeded 20% — transcription severely degraded",
        baseline=0.06,
    ),
    Rule(
        rule_id="STT_LOW_CONFIDENCE",
        dtc_code="STT-002",
        stage="transcription",
        metric="stt_word_error_rate",
        condition=lambda v: v > 0.15,
        severity=Severity.WARN,
        message="STT WER above 15% — early warning of transcription quality degradation",
        baseline=0.06,
    ),
    Rule(
        rule_id="STT_LOW_CONFIDENCE_SCORE",
        dtc_code="STT-003",
        stage="transcription",
        metric="stt_confidence_score",
        condition=lambda v: 0 < v < 0.70,   # 0 means metric not yet populated
        severity=Severity.WARN,
        message="Whisper confidence score below 0.70 — poor audio quality reducing transcription reliability",
        baseline=0.88,
    ),
    Rule(
        rule_id="STT_LOW_SPEECH_RATIO",
        dtc_code="STT-004",
        stage="transcription",
        metric="audio_speech_ratio",
        condition=lambda v: 0 < v < 0.40,
        severity=Severity.WARN,
        message="Speech ratio below 40% — student audio contains excessive silence or non-speech",
        baseline=0.82,
    ),

    # ── Feedback Generation (FBK) ────────────────────────────────────
    Rule(
        rule_id="FBK_LATENCY_SPIKE",
        dtc_code="FBK-001",
        stage="feedback",
        metric="feedback_api_latency_p99_ms",
        condition=lambda v: v > 5000,
        severity=Severity.WARN,
        message="GPT-4o feedback API P99 latency exceeded 5000 ms — response time severely degraded",
        baseline=1800.0,
    ),
    Rule(
        rule_id="FBK_RATE_LIMIT",
        dtc_code="FBK-002",
        stage="feedback",
        metric="feedback_error_rate_429",
        condition=lambda v: v > 0.10,
        severity=Severity.CRITICAL,
        message="GPT-4o API rate limiting active — >10% of feedback requests returning 429",
        baseline=0.0,
    ),
    Rule(
        rule_id="FBK_POOR_QUALITY",
        dtc_code="FBK-003",
        stage="feedback",
        metric="feedback_overall_score",
        condition=lambda v: 0 < v < 5.0,   # 0 means metric not yet populated
        severity=Severity.WARN,
        message="Feedback overall score below 5.0/10 — GPT-4o producing low-quality assessments",
        baseline=7.4,
    ),

    # ── System / Infrastructure (SYS) ───────────────────────────────
    Rule(
        rule_id="HIGH_CPU",
        dtc_code="SYS-001",
        stage="system",
        metric="system_cpu_percent",
        condition=lambda v: v > 85.0,
        severity=Severity.WARN,
        message="CPU utilisation above 85% — Celery workers may be throttled",
        baseline=30.0,
    ),
    Rule(
        rule_id="HIGH_MEMORY",
        dtc_code="SYS-002",
        stage="system",
        metric="system_memory_percent",
        condition=lambda v: v > 90.0,
        severity=Severity.CRITICAL,
        message="Memory utilisation above 90% — OOM risk for audio processing buffers",
        baseline=40.0,
    ),
    Rule(
        rule_id="PIPELINE_TIMEOUT",
        dtc_code="SYS-003",
        stage="pipeline",
        metric="pipeline_e2e_latency_p99_ms",
        condition=lambda v: v > 8000,
        severity=Severity.CRITICAL,
        message="End-to-end pipeline P99 latency exceeded 8 s — Celery task effectively timed out",
        baseline=2000.0,
    ),
]
