"""Tests for Z-score anomaly detector."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from diagnostics.anomaly_detector import AnomalyDetector


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
