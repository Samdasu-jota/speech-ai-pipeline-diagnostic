"""Tests for diagnostic rule evaluation."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from diagnostics.rules import RULES, Rule, Severity


def _snapshot(**kwargs):
    """Build a minimal metric snapshot."""
    defaults = {
        "stt_word_error_rate": 0.06,
        "audio_snr_db": 22.0,
        "llm_api_latency_p99_ms": 800.0,
        "llm_error_rate_429": 0.0,
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

    def test_current_value_captured(self):
        rule = next(r for r in RULES if r.rule_id == "STT_HIGH_WER")
        result = rule.evaluate(_snapshot(stt_word_error_rate=0.30))
        assert abs(result.current_value - 0.30) < 1e-9


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


class TestLLMRateLimit:
    def test_triggered_when_rate_exceeds_10_pct(self):
        rule = next(r for r in RULES if r.rule_id == "LLM_RATE_LIMIT")
        result = rule.evaluate(_snapshot(llm_error_rate_429=0.45))
        assert result.triggered
        assert result.severity == Severity.CRITICAL

    def test_not_triggered_at_healthy_rate(self):
        rule = next(r for r in RULES if r.rule_id == "LLM_RATE_LIMIT")
        result = rule.evaluate(_snapshot(llm_error_rate_429=0.02))
        assert not result.triggered


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

    def test_healthy_snapshot_fires_no_rules(self):
        snap = _snapshot()
        triggered = [r for r in RULES if r.evaluate(snap).triggered]
        assert len(triggered) == 0, f"Unexpected alerts on healthy snapshot: {[r.rule_id for r in triggered]}"
