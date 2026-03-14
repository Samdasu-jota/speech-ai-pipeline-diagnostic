"""
PipelineRunner — orchestrates the full speech AI pipeline.

Mirrors the Self English Tutor app's Celery task flow:
  Preprocessing → Transcription → Storage/Queue → Feedback Generation

Wires together AudioStage → STTStage → StorageStage → FeedbackStage
and records per-stage and end-to-end latency with correlation IDs.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from monitoring.metrics_registry import MetricsRegistry
from pipeline.audio_stage import AudioStage, AudioFrame
from pipeline.stt_stage import STTStage, STTResult
from pipeline.storage_stage import StorageStage, StorageResult
from pipeline.feedback_stage import FeedbackStage, FeedbackResult

logger = logging.getLogger(__name__)


@dataclass
class PipelineRunResult:
    session_id: str
    request_id: str
    feedback: Optional[FeedbackResult]
    e2e_latency_ms: float
    success: bool
    failed_stage: Optional[str] = None
    error_message: Optional[str] = None
    stage_latencies: dict[str, float] = field(default_factory=dict)


class PipelineRunner:
    """
    Runs a single end-to-end pipeline request.

    Stage sequence:
      1. Preprocessing (audio_stage) — simulate VAD + noise reduction
      2. Transcription (stt_stage)   — Whisper API
      3. Storage/Queue (storage_stage) — S3 upload + Celery dispatch
      4. Feedback (feedback_stage)   — GPT-4o structured feedback
    """

    def __init__(self) -> None:
        self.audio = AudioStage()
        self.stt = STTStage()
        self.storage = StorageStage()
        self.feedback = FeedbackStage()
        self.registry = MetricsRegistry.instance()

    def run(
        self,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> PipelineRunResult:
        session_id = session_id or f"sess-{uuid.uuid4().hex[:8]}"
        request_id = request_id or f"req-{uuid.uuid4().hex[:8]}"
        e2e_start = time.monotonic()

        logger.info(
            "pipeline_run_started",
            extra={"session_id": session_id, "request_id": request_id},
        )

        stage_latencies: dict[str, float] = {}

        try:
            # Stage 1 — Preprocessing
            t = time.monotonic()
            frame: AudioFrame = self.audio.capture(
                session_id=session_id, request_id=request_id
            )
            stage_latencies["preprocessing"] = (time.monotonic() - t) * 1000

            # Stage 2 — Transcription
            t = time.monotonic()
            stt: STTResult = self.stt.transcribe(
                frame, session_id=session_id, request_id=request_id
            )
            stage_latencies["transcription"] = (time.monotonic() - t) * 1000

            # Stage 3 — Storage / Queue
            t = time.monotonic()
            storage: StorageResult = self.storage.upload_and_enqueue(
                stt, session_id=session_id, request_id=request_id
            )
            stage_latencies["storage"] = (time.monotonic() - t) * 1000

            # Stage 4 — Feedback Generation
            t = time.monotonic()
            fbk: FeedbackResult = self.feedback.generate(
                stt, session_id=session_id, request_id=request_id
            )
            stage_latencies["feedback"] = (time.monotonic() - t) * 1000

            e2e_ms = (time.monotonic() - e2e_start) * 1000
            self.registry.pipeline_e2e_latency_ms.observe(e2e_ms)
            self.registry.set_metric("pipeline_e2e_latency_p99_ms", e2e_ms)
            self.registry.pipeline_request_total.inc()

            logger.info(
                "pipeline_run_completed",
                extra={
                    "session_id": session_id,
                    "request_id": request_id,
                    "e2e_latency_ms": round(e2e_ms, 2),
                    "overall_score": fbk.overall_score,
                    "job_id": storage.job_id,
                },
            )
            return PipelineRunResult(
                session_id=session_id,
                request_id=request_id,
                feedback=fbk,
                e2e_latency_ms=e2e_ms,
                success=True,
                stage_latencies=stage_latencies,
            )

        except Exception as exc:
            e2e_ms = (time.monotonic() - e2e_start) * 1000
            failed_stage = _detect_failed_stage(stage_latencies)
            logger.error(
                "pipeline_run_failed",
                extra={
                    "session_id": session_id,
                    "request_id": request_id,
                    "e2e_latency_ms": round(e2e_ms, 2),
                    "failed_stage": failed_stage,
                    "error": str(exc),
                },
                exc_info=True,
            )
            return PipelineRunResult(
                session_id=session_id,
                request_id=request_id,
                feedback=None,
                e2e_latency_ms=e2e_ms,
                success=False,
                failed_stage=failed_stage,
                error_message=str(exc),
                stage_latencies=stage_latencies,
            )

    async def run_async(
        self,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> PipelineRunResult:
        """Async wrapper — runs the synchronous pipeline in a thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.run, session_id, request_id)


def _detect_failed_stage(stage_latencies: dict[str, float]) -> str:
    """Infer which stage failed based on which is the last completed stage."""
    stage_order = ["preprocessing", "transcription", "storage", "feedback"]
    last_completed = None
    for stage in stage_order:
        if stage in stage_latencies:
            last_completed = stage
    if last_completed is None:
        return "preprocessing"
    idx = stage_order.index(last_completed)
    return stage_order[idx + 1] if idx + 1 < len(stage_order) else last_completed
