"""
Diagnostic rules — threshold-based fault detection with DTC-style codes.

Each Rule maps a metric name to a condition function and fires a RuleResult
when the condition is met. Rules use DTC-style IDs (e.g., STT-001) to mirror
the conventions of automotive OBD-II diagnostic trouble codes.
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
    Rule(
        rule_id="STT_HIGH_WER",
        dtc_code="STT-001",
        stage="speech_to_text",
        metric="stt_word_error_rate",
        condition=lambda v: v > 0.20,
        severity=Severity.CRITICAL,
        message="STT Word Error Rate exceeded 20% — transcription severely degraded",
        baseline=0.06,
    ),
    Rule(
        rule_id="STT_LOW_CONFIDENCE",
        dtc_code="STT-002",
        stage="speech_to_text",
        metric="stt_word_error_rate",   # confidence tracked via WER proxy in mock
        condition=lambda v: v > 0.15,
        severity=Severity.WARN,
        message="STT confidence scores falling — possible audio quality issue",
        baseline=0.06,
    ),
    Rule(
        rule_id="LOW_AUDIO_SNR",
        dtc_code="AUD-001",
        stage="audio_capture",
        metric="audio_snr_db",
        condition=lambda v: v < 10.0,
        severity=Severity.WARN,
        message="Audio SNR below 10 dB — background noise likely affecting quality",
        baseline=22.0,
    ),
    Rule(
        rule_id="LLM_LATENCY_SPIKE",
        dtc_code="LLM-001",
        stage="llm",
        metric="llm_api_latency_p99_ms",
        condition=lambda v: v > 3000,
        severity=Severity.WARN,
        message="LLM API P99 latency exceeded 3000 ms — response time degraded",
        baseline=800.0,
    ),
    Rule(
        rule_id="LLM_RATE_LIMIT",
        dtc_code="LLM-002",
        stage="llm",
        metric="llm_error_rate_429",
        condition=lambda v: v > 0.10,
        severity=Severity.CRITICAL,
        message="LLM API rate limiting active — >10% of requests returning 429",
        baseline=0.0,
    ),
    Rule(
        rule_id="HIGH_CPU",
        dtc_code="SYS-001",
        stage="system",
        metric="system_cpu_percent",
        condition=lambda v: v > 85.0,
        severity=Severity.WARN,
        message="CPU utilisation above 85% — pipeline may be throttled",
        baseline=30.0,
    ),
    Rule(
        rule_id="HIGH_MEMORY",
        dtc_code="SYS-002",
        stage="system",
        metric="system_memory_percent",
        condition=lambda v: v > 90.0,
        severity=Severity.CRITICAL,
        message="Memory utilisation above 90% — OOM risk",
        baseline=40.0,
    ),
    Rule(
        rule_id="PIPELINE_TIMEOUT",
        dtc_code="SYS-003",
        stage="pipeline",
        metric="pipeline_e2e_latency_p99_ms",
        condition=lambda v: v > 8000,
        severity=Severity.CRITICAL,
        message="End-to-end pipeline P99 latency exceeded 8 s — pipeline effectively timed out",
        baseline=2000.0,
    ),
]
