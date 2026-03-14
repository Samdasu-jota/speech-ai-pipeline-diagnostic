"""Tests for PipelineRunner end-to-end execution.

Pipeline stages (aligned with Self English Tutor app):
  1. preprocessing  — AudioStage (VAD, noise reduction)
  2. transcription  — STTStage (Whisper)
  3. storage        — StorageStage (S3 + Celery queue)
  4. feedback       — FeedbackStage (GPT-4o)
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
import pytest
from pipeline.pipeline_runner import PipelineRunner
from monitoring.metrics_registry import MetricsRegistry


@pytest.fixture(autouse=True)
def reset_registry():
    MetricsRegistry._instance = None
    yield
    MetricsRegistry._instance = None


class TestPipelineRunner:
    def test_successful_run_returns_result(self):
        runner = PipelineRunner()
        result = runner.run()
        assert result.success is True
        assert result.feedback is not None
        assert result.e2e_latency_ms > 0

    def test_feedback_contains_scores(self):
        runner = PipelineRunner()
        result = runner.run()
        assert result.feedback is not None
        assert 0.0 <= result.feedback.grammar_score <= 10.0
        assert 0.0 <= result.feedback.overall_score <= 10.0

    def test_stage_latencies_populated(self):
        runner = PipelineRunner()
        result = runner.run()
        for stage in ("preprocessing", "transcription", "storage", "feedback"):
            assert stage in result.stage_latencies, f"Missing stage: {stage}"
            assert result.stage_latencies[stage] > 0

    def test_old_stage_names_not_present(self):
        runner = PipelineRunner()
        result = runner.run()
        for old_stage in ("audio", "stt", "nlp", "llm", "output"):
            assert old_stage not in result.stage_latencies, f"Old stage still present: {old_stage}"

    def test_correlation_ids_assigned(self):
        runner = PipelineRunner()
        result = runner.run()
        assert result.session_id.startswith("sess-")
        assert result.request_id.startswith("req-")

    def test_custom_session_id_propagated(self):
        runner = PipelineRunner()
        result = runner.run(session_id="sess-custom-123")
        assert result.session_id == "sess-custom-123"

    def test_e2e_latency_recorded_in_registry(self):
        runner = PipelineRunner()
        runner.run()
        registry = MetricsRegistry.instance()
        snapshot = registry.snapshot()
        assert snapshot.get("pipeline_e2e_latency_p99_ms", 0.0) > 0

    def test_confidence_metric_recorded_in_registry(self):
        runner = PipelineRunner()
        runner.run()
        registry = MetricsRegistry.instance()
        snapshot = registry.snapshot()
        # Whisper confidence should be populated after a run
        assert snapshot.get("stt_confidence_score", 0.0) > 0

    def test_feedback_scores_recorded_in_registry(self):
        runner = PipelineRunner()
        runner.run()
        registry = MetricsRegistry.instance()
        snapshot = registry.snapshot()
        assert snapshot.get("feedback_overall_score", 0.0) > 0

    def test_async_run_returns_same_result(self):
        runner = PipelineRunner()
        result = asyncio.run(runner.run_async())
        assert result.success is True
        assert result.feedback is not None
