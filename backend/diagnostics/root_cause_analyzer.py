"""
Root Cause Analyzer — causal graph mapping alert combinations to root causes.

Instead of reporting individual alert firings in isolation, the RCA module
correlates active alerts across multiple pipeline stages and produces a
structured root cause with evidence, confidence, and a suggested fix.

This mirrors the diagnostic philosophy in service engineering: a single
sensor reading is often ambiguous, but the combination of multiple readings
narrows the fault to a specific component or cause.

Causal rules are aligned with the Self English Tutor app's pipeline stages:
  Preprocessing → Transcription → Storage/Queue → Feedback Generation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from diagnostics.rules import RuleResult

logger = logging.getLogger(__name__)


@dataclass
class RCAResult:
    probable_cause: str
    confidence: float           # 0.0 – 1.0
    evidence: list[str]
    suggested_fix: str
    matched_rule_id: str
    affected_stages: list[str]


@dataclass
class CausalRule:
    """
    A causal rule matches a set of alert IDs to a root cause.

    `required` alerts must ALL be present.
    `optional` alerts increase confidence if present.
    """

    rule_id: str
    required_alerts: frozenset[str]
    optional_alerts: frozenset[str]
    base_confidence: float
    confidence_boost_per_optional: float
    probable_cause: str
    suggested_fix: str
    affected_stages: list[str]

    def matches(self, fired_ids: set[str]) -> bool:
        return self.required_alerts.issubset(fired_ids)

    def confidence(self, fired_ids: set[str]) -> float:
        optional_hits = len(self.optional_alerts & fired_ids)
        return min(
            1.0,
            self.base_confidence + optional_hits * self.confidence_boost_per_optional,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Causal Rule Definitions
# ──────────────────────────────────────────────────────────────────────────────

_CAUSAL_RULES: list[CausalRule] = [
    # RCA-01: Noisy audio degrading transcription (SNR + WER combo)
    CausalRule(
        rule_id="RCA-01",
        required_alerts=frozenset({"STT_HIGH_WER", "LOW_AUDIO_SNR"}),
        optional_alerts=frozenset({"STT_LOW_CONFIDENCE", "ANOMALY_STT_WORD_ERROR_RATE"}),
        base_confidence=0.88,
        confidence_boost_per_optional=0.04,
        probable_cause="Microphone noise degrading transcription accuracy",
        suggested_fix=(
            "1. Enable noise filtering (e.g., WebRTC noise suppression). "
            "2. Check microphone placement and physical environment. "
            "3. Consider switching to a noise-robust STT model."
        ),
        affected_stages=["preprocessing", "transcription"],
    ),

    # RCA-02: Resource contention throttling Celery workers / GPT-4o calls
    CausalRule(
        rule_id="RCA-02",
        required_alerts=frozenset({"FBK_LATENCY_SPIKE", "HIGH_CPU"}),
        optional_alerts=frozenset({"PIPELINE_TIMEOUT", "ANOMALY_SYSTEM_CPU_PERCENT"}),
        base_confidence=0.82,
        confidence_boost_per_optional=0.05,
        probable_cause="Local resource contention throttling Celery workers and GPT-4o API calls",
        suggested_fix=(
            "1. Scale Celery worker concurrency or add worker nodes. "
            "2. Profile for CPU-bound operations in audio preprocessing. "
            "3. Add request queuing to prevent overload."
        ),
        affected_stages=["feedback", "system"],
    ),

    # RCA-03: GPT-4o API rate limit quota exceeded
    CausalRule(
        rule_id="RCA-03",
        required_alerts=frozenset({"FBK_RATE_LIMIT"}),
        optional_alerts=frozenset({"FBK_LATENCY_SPIKE", "ANOMALY_FEEDBACK_API_LATENCY_P99_MS"}),
        base_confidence=0.95,
        confidence_boost_per_optional=0.02,
        probable_cause="GPT-4o API rate limit quota exceeded",
        suggested_fix=(
            "1. Implement exponential backoff and retry logic (Celery retry with countdown). "
            "2. Review request rate — batch feedback requests where possible. "
            "3. Request quota increase from OpenAI."
        ),
        affected_stages=["feedback"],
    ),

    # RCA-04: External GPT-4o API latency degradation
    CausalRule(
        rule_id="RCA-04",
        required_alerts=frozenset({"FBK_LATENCY_SPIKE"}),
        optional_alerts=frozenset({"ANOMALY_FEEDBACK_API_LATENCY_P99_MS"}),
        base_confidence=0.72,
        confidence_boost_per_optional=0.08,
        probable_cause="External GPT-4o API latency degradation (network or OpenAI provider-side)",
        suggested_fix=(
            "1. Check OpenAI status page (status.openai.com). "
            "2. Add per-request timeout and circuit breaker in FeedbackStage. "
            "3. Consider caching feedback for identical transcripts."
        ),
        affected_stages=["feedback"],
    ),

    # RCA-05: Cascading failure — bad transcription → degraded GPT-4o output
    CausalRule(
        rule_id="RCA-05",
        required_alerts=frozenset({"STT_HIGH_WER", "FBK_LATENCY_SPIKE"}),
        optional_alerts=frozenset({"PIPELINE_TIMEOUT"}),
        base_confidence=0.78,
        confidence_boost_per_optional=0.07,
        probable_cause="Cascading pipeline failure — degraded Whisper transcription causing GPT-4o errors",
        suggested_fix=(
            "1. Add input confidence gate: reject transcripts with confidence < 0.60 before GPT-4o call. "
            "2. Implement STT fallback for high-WER sessions. "
            "3. Return partial feedback noting transcription quality issue."
        ),
        affected_stages=["transcription", "feedback"],
    ),

    # RCA-06: Pipeline end-to-end timeout (cumulative stage latency)
    CausalRule(
        rule_id="RCA-06",
        required_alerts=frozenset({"PIPELINE_TIMEOUT"}),
        optional_alerts=frozenset({"HIGH_CPU", "FBK_LATENCY_SPIKE"}),
        base_confidence=0.70,
        confidence_boost_per_optional=0.08,
        probable_cause="Pipeline end-to-end timeout — cumulative Celery task latency exceeded threshold",
        suggested_fix=(
            "1. Profile each stage for individual latency contributors. "
            "2. Enforce per-stage Celery task timeouts with graceful degradation. "
            "3. Parallelise independent pipeline stages where dependencies allow."
        ),
        affected_stages=["pipeline"],
    ),

    # RCA-07: Memory pressure
    CausalRule(
        rule_id="RCA-07",
        required_alerts=frozenset({"HIGH_MEMORY"}),
        optional_alerts=frozenset({"HIGH_CPU", "PIPELINE_TIMEOUT"}),
        base_confidence=0.88,
        confidence_boost_per_optional=0.04,
        probable_cause="Memory pressure causing system instability — audio processing buffers may be leaking",
        suggested_fix=(
            "1. Profile Celery workers for memory leaks (especially pydub / torch VAD buffers). "
            "2. Reduce in-memory audio buffer sizes; stream to S3 earlier. "
            "3. Scale vertical memory or set container memory limits to force OOM restarts."
        ),
        affected_stages=["system"],
    ),

    # RCA-08: Noisy audio degrading Whisper confidence specifically
    CausalRule(
        rule_id="RCA-08",
        required_alerts=frozenset({"STT_HIGH_WER", "STT_LOW_CONFIDENCE_SCORE", "LOW_AUDIO_SNR"}),
        optional_alerts=frozenset({"AUD_NEAR_SILENT", "ANOMALY_STT_WORD_ERROR_RATE"}),
        base_confidence=0.93,
        confidence_boost_per_optional=0.03,
        probable_cause="Microphone noise degrading Whisper confidence and word-level accuracy simultaneously",
        suggested_fix=(
            "1. Enable spectral noise reduction (noisereduce) before Whisper API call. "
            "2. Verify silero-vad is properly filtering non-speech segments. "
            "3. Check microphone quality and room acoustics. "
            "4. Switch to Whisper large-v3 for better noise robustness."
        ),
        affected_stages=["preprocessing", "transcription"],
    ),

    # RCA-09: Poor transcription quality causing low-value GPT-4o feedback
    CausalRule(
        rule_id="RCA-09",
        required_alerts=frozenset({"FBK_POOR_QUALITY", "STT_LOW_CONFIDENCE_SCORE"}),
        optional_alerts=frozenset({"STT_HIGH_WER", "STT_LOW_SPEECH_RATIO"}),
        base_confidence=0.88,
        confidence_boost_per_optional=0.04,
        probable_cause=(
            "Poor Whisper transcription quality producing low-value GPT-4o feedback — "
            "garbage-in, garbage-out across the pipeline"
        ),
        suggested_fix=(
            "1. Gate the feedback stage: only call GPT-4o if confidence > 0.65. "
            "2. Return a 'retake' prompt to the student when transcription is too noisy. "
            "3. Pre-process audio more aggressively before Whisper (noise reduction + normalisation)."
        ),
        affected_stages=["transcription", "feedback"],
    ),

    # RCA-10: VAD / silence detection issue — student audio mostly silent
    CausalRule(
        rule_id="RCA-10",
        required_alerts=frozenset({"STT_LOW_SPEECH_RATIO"}),
        optional_alerts=frozenset({"AUD_NEAR_SILENT", "STT_LOW_CONFIDENCE_SCORE"}),
        base_confidence=0.80,
        confidence_boost_per_optional=0.06,
        probable_cause=(
            "VAD or silence detection issue — student audio contains insufficient speech. "
            "Possible causes: student didn't speak, microphone muted, or VAD threshold misconfigured."
        ),
        suggested_fix=(
            "1. Display a UI prompt if speech_ratio < 0.40: 'We couldn't hear you clearly — please try again.' "
            "2. Tune silero-vad sensitivity threshold for the deployment environment. "
            "3. Check that the mobile app is correctly requesting microphone permissions. "
            "4. Add minimum recording duration validation before upload."
        ),
        affected_stages=["preprocessing", "transcription"],
    ),
]

_FALLBACK_RCA = RCAResult(
    probable_cause="Undetermined — insufficient correlated evidence",
    confidence=0.30,
    evidence=["Multiple alerts fired but no causal pattern matched"],
    suggested_fix="Inspect individual alert details and stage-level metrics in Grafana.",
    matched_rule_id="RCA-FALLBACK",
    affected_stages=[],
)


class RootCauseAnalyzer:
    """
    Correlates fired alerts against a causal rule graph to identify root causes.

    Usage:
        rca = RootCauseAnalyzer()
        result = rca.analyze(fired_alerts)
    """

    def __init__(self) -> None:
        self._rules = _CAUSAL_RULES

    def analyze(self, fired: list[RuleResult]) -> RCAResult:
        fired_ids = {r.rule_id for r in fired}
        candidates: list[tuple[float, CausalRule]] = []

        for rule in self._rules:
            if rule.matches(fired_ids):
                conf = rule.confidence(fired_ids)
                candidates.append((conf, rule))

        if not candidates:
            logger.info(
                "rca_no_match",
                extra={"fired_ids": list(fired_ids)},
            )
            return _FALLBACK_RCA

        # Pick highest-confidence match
        best_conf, best_rule = max(candidates, key=lambda x: x[0])
        evidence = _build_evidence(fired, best_rule)

        result = RCAResult(
            probable_cause=best_rule.probable_cause,
            confidence=round(best_conf, 3),
            evidence=evidence,
            suggested_fix=best_rule.suggested_fix,
            matched_rule_id=best_rule.rule_id,
            affected_stages=best_rule.affected_stages,
        )
        logger.info(
            "rca_matched",
            extra={
                "rule_id": best_rule.rule_id,
                "confidence": round(best_conf, 3),
                "probable_cause": best_rule.probable_cause,
            },
        )
        return result


def _build_evidence(fired: list[RuleResult], rule: CausalRule) -> list[str]:
    evidence: list[str] = []
    for alert in fired:
        if alert.rule_id in rule.required_alerts or alert.rule_id in rule.optional_alerts:
            if alert.baseline_value is not None:
                evidence.append(
                    f"{alert.dtc_code}: {alert.message} "
                    f"(current={alert.current_value:.3f}, baseline={alert.baseline_value:.3f})"
                )
            else:
                evidence.append(f"{alert.dtc_code}: {alert.message} (current={alert.current_value:.3f})")
    return evidence
