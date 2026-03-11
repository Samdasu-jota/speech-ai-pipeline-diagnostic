"""
Root Cause Analyzer — causal graph mapping alert combinations to root causes.

Instead of reporting individual alert firings in isolation, the RCA module
correlates active alerts across multiple pipeline stages and produces a
structured root cause with evidence, confidence, and a suggested fix.

This mirrors the diagnostic philosophy in service engineering: a single
sensor reading is often ambiguous, but the combination of multiple readings
narrows the fault to a specific component or cause.
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
        affected_stages=["audio_capture", "speech_to_text"],
    ),
    CausalRule(
        rule_id="RCA-02",
        required_alerts=frozenset({"LLM_LATENCY_SPIKE", "HIGH_CPU"}),
        optional_alerts=frozenset({"PIPELINE_TIMEOUT", "ANOMALY_SYSTEM_CPU_PERCENT"}),
        base_confidence=0.82,
        confidence_boost_per_optional=0.05,
        probable_cause="Local resource contention throttling LLM API calls",
        suggested_fix=(
            "1. Scale compute resources or reduce concurrent pipeline requests. "
            "2. Profile for CPU-bound operations consuming cycles. "
            "3. Add request queuing to prevent overload."
        ),
        affected_stages=["llm", "system"],
    ),
    CausalRule(
        rule_id="RCA-03",
        required_alerts=frozenset({"LLM_RATE_LIMIT"}),
        optional_alerts=frozenset({"LLM_LATENCY_SPIKE", "ANOMALY_LLM_API_LATENCY_P99_MS"}),
        base_confidence=0.95,
        confidence_boost_per_optional=0.02,
        probable_cause="LLM API rate limit quota exceeded",
        suggested_fix=(
            "1. Implement exponential backoff and retry logic. "
            "2. Review request rate and batch where possible. "
            "3. Request quota increase from API provider."
        ),
        affected_stages=["llm"],
    ),
    CausalRule(
        rule_id="RCA-04",
        required_alerts=frozenset({"LLM_LATENCY_SPIKE"}),
        optional_alerts=frozenset({"ANOMALY_LLM_API_LATENCY_P99_MS"}),
        base_confidence=0.72,
        confidence_boost_per_optional=0.08,
        probable_cause="External LLM API latency degradation (network or provider-side)",
        suggested_fix=(
            "1. Check API provider status page. "
            "2. Add timeout + circuit breaker. "
            "3. Consider fallback to a local/cached response."
        ),
        affected_stages=["llm"],
    ),
    CausalRule(
        rule_id="RCA-05",
        required_alerts=frozenset({"STT_HIGH_WER", "LLM_LATENCY_SPIKE"}),
        optional_alerts=frozenset({"PIPELINE_TIMEOUT"}),
        base_confidence=0.78,
        confidence_boost_per_optional=0.07,
        probable_cause="Cascading pipeline failure — degraded STT output causing LLM errors",
        suggested_fix=(
            "1. Add input validation gate between STT and LLM stages. "
            "2. Reject or flag low-confidence transcripts before LLM call. "
            "3. Implement STT fallback for high-WER sessions."
        ),
        affected_stages=["speech_to_text", "llm"],
    ),
    CausalRule(
        rule_id="RCA-06",
        required_alerts=frozenset({"PIPELINE_TIMEOUT"}),
        optional_alerts=frozenset({"HIGH_CPU", "LLM_LATENCY_SPIKE"}),
        base_confidence=0.70,
        confidence_boost_per_optional=0.08,
        probable_cause="Pipeline end-to-end timeout — cumulative stage latency exceeded threshold",
        suggested_fix=(
            "1. Profile each stage for individual latency contributors. "
            "2. Enforce per-stage timeouts with graceful degradation. "
            "3. Run stages in async/parallel where dependencies allow."
        ),
        affected_stages=["pipeline"],
    ),
    CausalRule(
        rule_id="RCA-07",
        required_alerts=frozenset({"HIGH_MEMORY"}),
        optional_alerts=frozenset({"HIGH_CPU", "PIPELINE_TIMEOUT"}),
        base_confidence=0.88,
        confidence_boost_per_optional=0.04,
        probable_cause="Memory pressure causing system instability",
        suggested_fix=(
            "1. Profile for memory leaks in pipeline stages. "
            "2. Reduce in-memory audio buffer sizes. "
            "3. Scale vertical memory or containerise with hard limits."
        ),
        affected_stages=["system"],
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
