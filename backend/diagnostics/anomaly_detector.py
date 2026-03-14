"""
Anomaly Detector — Z-score based statistical fault detection.

Maintains a rolling window of observations for each metric and fires an
alert when a new value deviates more than `threshold` standard deviations
from the rolling mean. This catches gradual drift and subtle degradation
that fixed thresholds would miss.

Analogous to continuous telemetry monitoring in embedded diagnostics systems
where baseline characteristics must be learned from the signal stream itself.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass
from typing import Deque

from diagnostics.rules import RuleResult, Severity

logger = logging.getLogger(__name__)

# Metrics to watch for anomalies (these have no good fixed threshold)
# Aligned with Self English Tutor pipeline: Whisper confidence + GPT-4o grammar score
# are especially valuable for catching gradual quality drift.
_WATCHED_METRICS = [
    "stt_word_error_rate",
    "stt_confidence_score",
    "audio_snr_db",
    "feedback_api_latency_p99_ms",
    "feedback_grammar_score",
    "system_cpu_percent",
    "pipeline_e2e_latency_p99_ms",
]

_MIN_SAMPLES = 20  # Need at least this many before Z-score is meaningful


@dataclass
class _MetricWindow:
    values: Deque[float]
    window_size: int

    def push(self, v: float) -> None:
        self.values.append(v)
        if len(self.values) > self.window_size:
            self.values.popleft()

    def mean(self) -> float:
        return sum(self.values) / len(self.values)

    def stddev(self) -> float:
        if len(self.values) < 2:
            return 0.0
        m = self.mean()
        variance = sum((x - m) ** 2 for x in self.values) / (len(self.values) - 1)
        return math.sqrt(variance)

    def zscore(self, value: float) -> float:
        std = self.stddev()
        if std < 1e-9:
            return 0.0
        return (value - self.mean()) / std

    def ready(self) -> bool:
        return len(self.values) >= _MIN_SAMPLES


class AnomalyDetector:
    """
    Statistical anomaly detector using a rolling Z-score.

    Usage:
        detector = AnomalyDetector(window_size=300, threshold=3.0)
        anomalies = detector.evaluate(snapshot)
    """

    def __init__(self, window_size: int = 300, threshold: float = 3.0) -> None:
        self.window_size = window_size
        self.threshold = threshold
        self._windows: dict[str, _MetricWindow] = {
            m: _MetricWindow(deque(), window_size) for m in _WATCHED_METRICS
        }

    def evaluate(self, snapshot: dict[str, float]) -> list[RuleResult]:
        results: list[RuleResult] = []
        for metric in _WATCHED_METRICS:
            value = snapshot.get(metric)
            if value is None:
                continue
            window = self._windows[metric]
            if window.ready():
                z = window.zscore(value)
                if abs(z) >= self.threshold:
                    direction = "spike" if z > 0 else "drop"
                    result = RuleResult(
                        rule_id=f"ANOMALY_{metric.upper()}",
                        dtc_code=f"ANOM-{abs(int(z * 10)):03d}",
                        triggered=True,
                        severity=Severity.WARN if abs(z) < 5 else Severity.CRITICAL,
                        message=(
                            f"Statistical anomaly detected in {metric}: "
                            f"{direction} of {abs(z):.1f}σ (value={value:.3f}, "
                            f"mean={window.mean():.3f}, σ={window.stddev():.3f})"
                        ),
                        current_value=value,
                        baseline_value=window.mean(),
                        stage="anomaly_detector",
                    )
                    results.append(result)
                    logger.warning(
                        "anomaly_detected",
                        extra={
                            "metric": metric,
                            "z_score": round(z, 2),
                            "value": round(value, 4),
                            "mean": round(window.mean(), 4),
                            "stddev": round(window.stddev(), 4),
                        },
                    )
            # Always update window after evaluation
            window.push(value)
        return results

    def reset(self) -> None:
        """Clear all rolling windows (e.g., after a major system change)."""
        for window in self._windows.values():
            window.values.clear()
