"""Tests for Z-score anomaly detector.

Watches 7 metrics aligned with the Self English Tutor pipeline:
  stt_word_error_rate, stt_confidence_score, audio_snr_db,
  feedback_api_latency_p99_ms, feedback_grammar_score,
  system_cpu_percent, pipeline_e2e_latency_p99_ms
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from diagnostics.anomaly_detector import AnomalyDetector, _WATCHED_METRICS


def _warm_up(detector, metric, value, n=25):
    """Feed n identical values to populate the rolling window."""
    for _ in range(n):
        detector.evaluate({metric: value})


class TestAnomalyDetector:
    def test_no_alerts_before_min_samples(self):
        detector = AnomalyDetector(window_size=300, threshold=3.0)
        # Feed only 5 samples — below _MIN_SAMPLES=20
        for _ in range(5):
            alerts = detector.evaluate({"stt_word_error_rate": 0.06})
        assert alerts == []

    def test_no_alert_within_normal_range(self):
        detector = AnomalyDetector(window_size=300, threshold=3.0)
        _warm_up(detector, "stt_word_error_rate", 0.06)
        # Slight variation — should not trigger
        alerts = detector.evaluate({"stt_word_error_rate": 0.07})
        assert len(alerts) == 0

    def test_spike_triggers_anomaly(self):
        detector = AnomalyDetector(window_size=300, threshold=3.0)
        _warm_up(detector, "stt_word_error_rate", 0.06, n=30)
        # Massive spike — should exceed 3σ
        alerts = detector.evaluate({"stt_word_error_rate": 0.80})
        assert len(alerts) == 1
        assert "ANOMALY" in alerts[0].rule_id

    def test_drop_triggers_anomaly(self):
        detector = AnomalyDetector(window_size=300, threshold=3.0)
        _warm_up(detector, "audio_snr_db", 22.0, n=30)
        # Sudden SNR drop
        alerts = detector.evaluate({"audio_snr_db": 1.0})
        assert len(alerts) == 1

    def test_confidence_score_drop_triggers_anomaly(self):
        """Whisper confidence drop should be caught by anomaly detector."""
        detector = AnomalyDetector(window_size=300, threshold=3.0)
        _warm_up(detector, "stt_confidence_score", 0.88, n=30)
        # Confidence collapses to 0.35 — should trigger
        alerts = detector.evaluate({"stt_confidence_score": 0.35})
        assert len(alerts) == 1
        assert "STT_CONFIDENCE_SCORE" in alerts[0].rule_id

    def test_grammar_score_drop_triggers_anomaly(self):
        """GPT-4o grammar score degradation should be caught by anomaly detector."""
        detector = AnomalyDetector(window_size=300, threshold=3.0)
        _warm_up(detector, "feedback_grammar_score", 7.5, n=30)
        # Score collapses — should trigger
        alerts = detector.evaluate({"feedback_grammar_score": 2.0})
        assert len(alerts) == 1
        assert "FEEDBACK_GRAMMAR_SCORE" in alerts[0].rule_id

    def test_reset_clears_windows(self):
        detector = AnomalyDetector(window_size=300, threshold=3.0)
        _warm_up(detector, "stt_word_error_rate", 0.06, n=30)
        detector.reset()
        # After reset, no alerts should fire (window is empty)
        alerts = detector.evaluate({"stt_word_error_rate": 0.80})
        assert len(alerts) == 0

    def test_alert_has_correct_fields(self):
        detector = AnomalyDetector(window_size=300, threshold=3.0)
        _warm_up(detector, "system_cpu_percent", 30.0, n=30)
        alerts = detector.evaluate({"system_cpu_percent": 99.0})
        if alerts:
            a = alerts[0]
            assert a.triggered is True
            assert a.current_value == 99.0
            assert a.baseline_value is not None

    def test_watched_metrics_includes_new_tutor_metrics(self):
        """Verify that confidence and grammar score are in the watched list."""
        assert "stt_confidence_score" in _WATCHED_METRICS
        assert "feedback_grammar_score" in _WATCHED_METRICS

    def test_watched_metrics_uses_feedback_not_llm_names(self):
        """Verify old LLM metric names are not in watched list."""
        assert "llm_api_latency_p99_ms" not in _WATCHED_METRICS
        assert "feedback_api_latency_p99_ms" in _WATCHED_METRICS
