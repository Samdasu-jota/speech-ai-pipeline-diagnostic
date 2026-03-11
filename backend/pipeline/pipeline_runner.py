"""
PipelineRunner — orchestrates the full speech AI pipeline.

Wires together Audio → STT → NLP → LLM → Output and records
the end-to-end latency and per-request correlation IDs.
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
from pipeline.nlp_stage import NLPStage, NLPResult
from pipeline.llm_stage import LLMStage, LLMResult
from pipeline.output_stage import OutputStage, PipelineResponse

logger = logging.getLogger(__name__)


@dataclass
class PipelineRunResult:
    session_id: str
    request_id: str
    response: Optional[PipelineResponse]
    e2e_latency_ms: float
    success: bool
    failed_stage: Optional[str] = None
    error_message: Optional[str] = None
    stage_latencies: dict[str, float] = field(default_factory=dict)


class PipelineRunner:
    """
    Runs a single end-to-end pipeline request.

    Each stage is executed sequentially and its output passed to the next.
    The runner records per-request timing and pushes the E2E latency to
    the MetricsRegistry.
    """

    def __init__(self) -> None:
        self.audio = AudioStage()
        self.stt = STTStage()
        self.nlp = NLPStage()
        self.llm = LLMStage()
        self.output = OutputStage()
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
            # Stage 1 — Audio Capture
            t = time.monotonic()
            frame: AudioFrame = self.audio.capture(
                session_id=session_id, request_id=request_id
            )
            stage_latencies["audio"] = (time.monotonic() - t) * 1000

            # Stage 2 — Speech-to-Text
            t = time.monotonic()
            stt: STTResult = self.stt.transcribe(
                frame, session_id=session_id, request_id=request_id
            )
            stage_latencies["stt"] = (time.monotonic() - t) * 1000

            # Stage 3 — NLP
            t = time.monotonic()
            nlp: NLPResult = self.nlp.process(
                stt, session_id=session_id, request_id=request_id
            )
            stage_latencies["nlp"] = (time.monotonic() - t) * 1000

            # Stage 4 — LLM
            t = time.monotonic()
            llm: LLMResult = self.llm.correct(
                nlp, session_id=session_id, request_id=request_id
            )
            stage_latencies["llm"] = (time.monotonic() - t) * 1000

            # Stage 5 — Output
            t = time.monotonic()
            resp: PipelineResponse = self.output.deliver(
                llm, session_id=session_id, request_id=request_id
            )
            stage_latencies["output"] = (time.monotonic() - t) * 1000

            e2e_ms = (time.monotonic() - e2e_start) * 1000
            self.registry.pipeline_e2e_latency_ms.observe(e2e_ms)
            self.registry.set_metric("pipeline_e2e_latency_p99_ms", e2e_ms)  # simplified: set last value
            self.registry.pipeline_request_total.inc()

            logger.info(
                "pipeline_run_completed",
                extra={
                    "session_id": session_id,
                    "request_id": request_id,
                    "e2e_latency_ms": round(e2e_ms, 2),
                },
            )
            return PipelineRunResult(
                session_id=session_id,
                request_id=request_id,
                response=resp,
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
                response=None,
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
    stage_order = ["audio", "stt", "nlp", "llm", "output"]
    last_completed = None
    for stage in stage_order:
        if stage in stage_latencies:
            last_completed = stage
    if last_completed is None:
        return "audio"
    idx = stage_order.index(last_completed)
    return stage_order[idx + 1] if idx + 1 < len(stage_order) else last_completed
