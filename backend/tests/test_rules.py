"""Tests for diagnostic rule evaluation.

Rules are aligned with the Self English Tutor pipeline stages:
  AUD-001/002  Preprocessing  (SNR, speech ratio)
  STT-001/002/003/004  Transcription  (WER, confidence, speech ratio)
  FBK-001/002/003  Feedback  (GPT-4o latency, rate limit, quality)
  SYS-001/002/003  System / pipeline
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from diagnostics.rules import RULES, Rule, Severity


def _snapshot(**kwargs):
    """Build a minimal healthy metric snapshot."""
    defaults = {
        "stt_word_error_rate": 0.06,
        "stt_confidence_score": 0.88,
        "audio_snr_db": 22.0,
        "audio_speech_ratio": 0.82,
        "feedback_api_latency_p99_ms": 1800.0,
        "feedback_error_rate_429": 0.0,
        "feedback_overall_score": 7.4,
        "system_cpu_percent": 30.0,
        "system_memory_percent": 40.0,
        "pipeline_e2e_latency_p99_ms": 2000.0,
    }
    defaults.update(kwargs)
    return defaults


class TestSTTHighWER:
    def test_not_triggered_below_threshold(self):
        rule = next(r for r in RULES if r.rule_id == "STT_HIGH_WER")
        result = rule.evaluate(_snapshot(stt_word_error_rate=0.15))
        assert not result.triggered

    def test_triggered_at_threshold(self):
        rule = next(r for r in RULES if r.rule_id == "STT_HIGH_WER")
        result = rule.evaluate(_snapshot(stt_word_error_rate=0.21))
        assert result.triggered
        assert result.severity == Severity.CRITICAL

    def test_dtc_code_format(self):
        rule = next(r for r in RULES if r.rule_id == "STT_HIGH_WER")
        result = rule.evaluate(_snapshot(stt_word_error_rate=0.25))
        assert result.dtc_code == "STT-001"

    def test_stage_is_transcription(self):
        rule = next(r for r in RULES if r.rule_id == "STT_HIGH_WER")
        assert rule.stage == "transcription"


class TestLowAudioSNR:
    def test_not_triggered_above_threshold(self):
        rule = next(r for r in RULES if r.rule_id == "LOW_AUDIO_SNR")
        result = rule.evaluate(_snapshot(audio_snr_db=15.0))
        assert not result.triggered

    def test_triggered_below_threshold(self):
        rule = next(r for r in RULES if r.rule_id == "LOW_AUDIO_SNR")
        result = rule.evaluate(_snapshot(audio_snr_db=7.2))
        assert result.triggered
        assert result.severity == Severity.WARN

    def test_dtc_code(self):
        rule = next(r for r in RULES if r.rule_id == "LOW_AUDIO_SNR")
        assert rule.dtc_code == "AUD-001"
        assert rule.stage == "preprocessing"


class TestAudNearSilent:
    def test_triggered_when_mostly_silence(self):
        rule = next(r for r in RULES if r.rule_id == "AUD_NEAR_SILENT")
        result = rule.evaluate(_snapshot(audio_speech_ratio=0.15))
        assert result.triggered
        assert result.severity == Severity.CRITICAL

    def test_not_triggered_at_healthy_ratio(self):
        rule = next(r for r in RULES if r.rule_id == "AUD_NEAR_SILENT")
        result = rule.evaluate(_snapshot(audio_speech_ratio=0.82))
        assert not result.triggered

    def test_dtc_code(self):
        rule = next(r for r in RULES if r.rule_id == "AUD_NEAR_SILENT")
        assert rule.dtc_code == "AUD-002"


class TestSTTLowConfidenceScore:
    def test_triggered_when_confidence_low(self):
        rule = next(r for r in RULES if r.rule_id == "STT_LOW_CONFIDENCE_SCORE")
        result = rule.evaluate(_snapshot(stt_confidence_score=0.55))
        assert result.triggered
        assert result.severity == Severity.WARN

    def test_not_triggered_at_healthy_confidence(self):
        rule = next(r for r in RULES if r.rule_id == "STT_LOW_CONFIDENCE_SCORE")
        result = rule.evaluate(_snapshot(stt_confidence_score=0.88))
        assert not result.triggered

    def test_not_triggered_at_zero_uninitialised(self):
        # 0.0 means metric not yet set — should not fire
        rule = next(r for r in RULES if r.rule_id == "STT_LOW_CONFIDENCE_SCORE")
        result = rule.evaluate(_snapshot(stt_confidence_score=0.0))
        assert not result.triggered

    def test_dtc_code(self):
        rule = next(r for r in RULES if r.rule_id == "STT_LOW_CONFIDENCE_SCORE")
        assert rule.dtc_code == "STT-003"


class TestSTTLowSpeechRatio:
    def test_triggered_when_speech_ratio_low(self):
        rule = next(r for r in RULES if r.rule_id == "STT_LOW_SPEECH_RATIO")
        result = rule.evaluate(_snapshot(audio_speech_ratio=0.30))
        assert result.triggered
        assert result.severity == Severity.WARN

    def test_not_triggered_at_healthy_ratio(self):
        rule = next(r for r in RULES if r.rule_id == "STT_LOW_SPEECH_RATIO")
        result = rule.evaluate(_snapshot(audio_speech_ratio=0.82))
        assert not result.triggered

    def test_dtc_code(self):
        rule = next(r for r in RULES if r.rule_id == "STT_LOW_SPEECH_RATIO")
        assert rule.dtc_code == "STT-004"


class TestFBKRateLimit:
    def test_triggered_when_rate_exceeds_10_pct(self):
        rule = next(r for r in RULES if r.rule_id == "FBK_RATE_LIMIT")
        result = rule.evaluate(_snapshot(feedback_error_rate_429=0.45))
        assert result.triggered
        assert result.severity == Severity.CRITICAL

    def test_not_triggered_at_healthy_rate(self):
        rule = next(r for r in RULES if r.rule_id == "FBK_RATE_LIMIT")
        result = rule.evaluate(_snapshot(feedback_error_rate_429=0.02))
        assert not result.triggered

    def test_dtc_code(self):
        rule = next(r for r in RULES if r.rule_id == "FBK_RATE_LIMIT")
        assert rule.dtc_code == "FBK-002"
        assert rule.stage == "feedback"


class TestFBKLatencySpike:
    def test_triggered_over_5s(self):
        rule = next(r for r in RULES if r.rule_id == "FBK_LATENCY_SPIKE")
        result = rule.evaluate(_snapshot(feedback_api_latency_p99_ms=5500.0))
        assert result.triggered
        assert result.severity == Severity.WARN

    def test_not_triggered_at_healthy_latency(self):
        rule = next(r for r in RULES if r.rule_id == "FBK_LATENCY_SPIKE")
        result = rule.evaluate(_snapshot(feedback_api_latency_p99_ms=1800.0))
        assert not result.triggered

    def test_dtc_code(self):
        rule = next(r for r in RULES if r.rule_id == "FBK_LATENCY_SPIKE")
        assert rule.dtc_code == "FBK-001"


class TestFBKPoorQuality:
    def test_triggered_when_score_low(self):
        rule = next(r for r in RULES if r.rule_id == "FBK_POOR_QUALITY")
        result = rule.evaluate(_snapshot(feedback_overall_score=4.2))
        assert result.triggered
        assert result.severity == Severity.WARN

    def test_not_triggered_at_healthy_score(self):
        rule = next(r for r in RULES if r.rule_id == "FBK_POOR_QUALITY")
        result = rule.evaluate(_snapshot(feedback_overall_score=7.4))
        assert not result.triggered

    def test_not_triggered_at_zero_uninitialised(self):
        rule = next(r for r in RULES if r.rule_id == "FBK_POOR_QUALITY")
        result = rule.evaluate(_snapshot(feedback_overall_score=0.0))
        assert not result.triggered

    def test_dtc_code(self):
        rule = next(r for r in RULES if r.rule_id == "FBK_POOR_QUALITY")
        assert rule.dtc_code == "FBK-003"


class TestPipelineTimeout:
    def test_triggered_over_8s(self):
        rule = next(r for r in RULES if r.rule_id == "PIPELINE_TIMEOUT")
        result = rule.evaluate(_snapshot(pipeline_e2e_latency_p99_ms=9000.0))
        assert result.triggered

    def test_missing_metric_defaults_to_zero(self):
        rule = next(r for r in RULES if r.rule_id == "PIPELINE_TIMEOUT")
        result = rule.evaluate({})   # empty snapshot
        assert not result.triggered  # 0 < 8000


class TestAllRules:
    def test_all_rules_have_dtc_codes(self):
        for rule in RULES:
            assert rule.dtc_code, f"Rule {rule.rule_id} missing DTC code"

    def test_all_rules_have_stages(self):
        for rule in RULES:
            assert rule.stage, f"Rule {rule.rule_id} missing stage"

    def test_healthy_snapshot_fires_no_rules(self):
        snap = _snapshot()
        triggered = [r for r in RULES if r.evaluate(snap).triggered]
        assert len(triggered) == 0, f"Unexpected alerts on healthy snapshot: {[r.rule_id for r in triggered]}"

    def test_rule_count(self):
        # 2 AUD + 4 STT + 3 FBK + 3 SYS = 12 total
        assert len(RULES) == 12
