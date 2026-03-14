"""Tests for Root Cause Analyzer causal graph matching.

RCA rules are aligned with the Self English Tutor pipeline:
  RCA-01/08   Noisy audio → bad Whisper transcription
  RCA-02      CPU contention → GPT-4o latency
  RCA-03      GPT-4o rate limit
  RCA-04      External GPT-4o latency degradation
  RCA-05      Cascading: bad transcription → bad feedback
  RCA-06      Pipeline E2E timeout
  RCA-07      Memory pressure
  RCA-09      Low confidence → poor GPT-4o feedback quality
  RCA-10      VAD / silence detection issue
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from diagnostics.root_cause_analyzer import RootCauseAnalyzer
from diagnostics.rules import RuleResult, Severity


def _alert(rule_id: str, dtc: str, severity=Severity.WARN, value=0.5):
    return RuleResult(
        rule_id=rule_id,
        dtc_code=dtc,
        triggered=True,
        severity=severity,
        message=f"Test alert {rule_id}",
        current_value=value,
        baseline_value=0.0,
        stage="test",
    )


class TestRootCauseAnalyzer:
    def setup_method(self):
        self.rca = RootCauseAnalyzer()

    def test_noise_scenario_matches_rca01(self):
        fired = [
            _alert("STT_HIGH_WER", "STT-001", Severity.CRITICAL),
            _alert("LOW_AUDIO_SNR", "AUD-001", Severity.WARN),
        ]
        result = self.rca.analyze(fired)
        assert result.matched_rule_id == "RCA-01"
        assert "noise" in result.probable_cause.lower()
        assert result.confidence >= 0.85

    def test_feedback_rate_limit_matches_rca03(self):
        fired = [_alert("FBK_RATE_LIMIT", "FBK-002", Severity.CRITICAL)]
        result = self.rca.analyze(fired)
        assert result.matched_rule_id == "RCA-03"
        assert "rate limit" in result.probable_cause.lower()

    def test_cpu_plus_feedback_latency_matches_rca02(self):
        fired = [
            _alert("FBK_LATENCY_SPIKE", "FBK-001", Severity.WARN),
            _alert("HIGH_CPU", "SYS-001", Severity.WARN),
        ]
        result = self.rca.analyze(fired)
        assert result.matched_rule_id == "RCA-02"

    def test_fallback_when_no_match(self):
        fired = [_alert("UNKNOWN_RULE_XYZ", "XYZ-000")]
        result = self.rca.analyze(fired)
        assert result.matched_rule_id == "RCA-FALLBACK"
        assert result.confidence < 0.50

    def test_confidence_boosted_by_optional_alerts(self):
        # RCA-01 base confidence = 0.88; optional alerts should boost it
        fired_base = [
            _alert("STT_HIGH_WER", "STT-001", Severity.CRITICAL),
            _alert("LOW_AUDIO_SNR", "AUD-001", Severity.WARN),
        ]
        fired_with_optional = fired_base + [
            _alert("STT_LOW_CONFIDENCE", "STT-002", Severity.WARN),
        ]
        result_base = self.rca.analyze(fired_base)
        result_boosted = self.rca.analyze(fired_with_optional)
        assert result_boosted.confidence >= result_base.confidence

    def test_evidence_list_populated(self):
        fired = [
            _alert("STT_HIGH_WER", "STT-001", Severity.CRITICAL),
            _alert("LOW_AUDIO_SNR", "AUD-001", Severity.WARN),
        ]
        result = self.rca.analyze(fired)
        assert len(result.evidence) >= 1

    def test_cascading_failure_scenario_rca05(self):
        fired = [
            _alert("STT_HIGH_WER", "STT-001", Severity.CRITICAL),
            _alert("FBK_LATENCY_SPIKE", "FBK-001", Severity.WARN),
        ]
        result = self.rca.analyze(fired)
        assert result.matched_rule_id == "RCA-05"
        assert "cascading" in result.probable_cause.lower()

    def test_whisper_noise_confidence_matches_rca08(self):
        """RCA-08: SNR + WER + low confidence score → Whisper noise degradation."""
        fired = [
            _alert("STT_HIGH_WER", "STT-001", Severity.CRITICAL),
            _alert("STT_LOW_CONFIDENCE_SCORE", "STT-003", Severity.WARN, value=0.52),
            _alert("LOW_AUDIO_SNR", "AUD-001", Severity.WARN),
        ]
        result = self.rca.analyze(fired)
        assert result.matched_rule_id == "RCA-08"
        assert result.confidence >= 0.90
        assert "confidence" in result.probable_cause.lower()

    def test_poor_feedback_quality_from_bad_transcription_rca09(self):
        """RCA-09: Low confidence score + poor feedback quality → garbage-in-garbage-out."""
        fired = [
            _alert("FBK_POOR_QUALITY", "FBK-003", Severity.WARN, value=4.2),
            _alert("STT_LOW_CONFIDENCE_SCORE", "STT-003", Severity.WARN, value=0.55),
        ]
        result = self.rca.analyze(fired)
        assert result.matched_rule_id == "RCA-09"
        assert "transcription" in result.probable_cause.lower()

    def test_low_speech_ratio_matches_rca10(self):
        """RCA-10: Low speech ratio alone → VAD / silence detection issue."""
        fired = [
            _alert("STT_LOW_SPEECH_RATIO", "STT-004", Severity.WARN, value=0.30),
        ]
        result = self.rca.analyze(fired)
        assert result.matched_rule_id == "RCA-10"
        assert "vad" in result.probable_cause.lower() or "silence" in result.probable_cause.lower()

    def test_memory_pressure_matches_rca07(self):
        fired = [_alert("HIGH_MEMORY", "SYS-002", Severity.CRITICAL)]
        result = self.rca.analyze(fired)
        assert result.matched_rule_id == "RCA-07"
        assert "memory" in result.probable_cause.lower()
