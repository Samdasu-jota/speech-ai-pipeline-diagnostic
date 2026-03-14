"""
Storage / Queue Stage — mirrors the Self English Tutor app's S3 upload + Celery task dispatch.

In the real app this stage:
  1. Uploads the processed WAV to S3/MinIO (raw/ and processed/ prefixes)
  2. Creates a ProcessingJob record in PostgreSQL
  3. Dispatches process_audio_task to the Celery queue (Redis broker)

Here it simulates that behaviour, tracking:
  - S3 upload latency
  - Celery queue depth (pending tasks)

Both metrics can be injected by the FailureSimulator to test diagnostics
for queue backup and storage latency fault scenarios.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass

from monitoring.metrics_registry import MetricsRegistry
from monitoring.stage_monitor import StageMonitor
from pipeline.stt_stage import STTResult

logger = logging.getLogger(__name__)

_HEALTHY_UPLOAD_LATENCY_MS = 120.0   # S3 upload ~120ms baseline
_HEALTHY_QUEUE_DEPTH = 0.0


@dataclass
class StorageResult:
    recording_id: str
    job_id: str
    upload_latency_ms: float
    queue_depth: int
    s3_key: str


class StorageStage:
    """
    Simulates S3 upload and Celery task dispatch.

    Reads override values from MetricsRegistry (set by FailureSimulator)
    so queue-backup and storage-latency fault scenarios are reflected in
    live telemetry.
    """

    def __init__(self) -> None:
        self.monitor = StageMonitor("storage")
        self.registry = MetricsRegistry.instance()
        self._job_counter = 0

    def upload_and_enqueue(
        self,
        stt_result: STTResult,
        session_id: str = "-",
        request_id: str = "-",
    ) -> StorageResult:
        with self.monitor.track("upload", session_id=session_id, request_id=request_id):
            snap = self.registry.snapshot()

            # Read injected values (FailureSimulator overrides these for queue backup)
            injected_queue_depth = snap.get("celery_queue_depth", _HEALTHY_QUEUE_DEPTH)

            # Simulate S3 upload latency (increases when queue is backed up)
            queue_penalty = max(0.0, injected_queue_depth * 8.0)
            upload_latency_ms = (
                _HEALTHY_UPLOAD_LATENCY_MS
                + queue_penalty
                + random.gauss(0, 15)
            )
            upload_latency_ms = max(20.0, upload_latency_ms)
            time.sleep(upload_latency_ms / 1000)

            # Simulate queue depth jitter
            queue_depth = max(0, int(injected_queue_depth + random.gauss(0, 0.5)))

            # Push to Prometheus
            self.registry.set_metric("storage_upload_latency_ms", upload_latency_ms)
            self.registry.set_metric("celery_queue_depth", float(queue_depth))

            self._job_counter += 1
            recording_id = f"rec-{session_id[-6:]}-{self._job_counter:04d}"
            job_id = f"job-{request_id[-6:]}-{self._job_counter:04d}"
            s3_key = f"processed/{session_id}/{recording_id}.wav"

            result = StorageResult(
                recording_id=recording_id,
                job_id=job_id,
                upload_latency_ms=upload_latency_ms,
                queue_depth=queue_depth,
                s3_key=s3_key,
            )
            logger.debug(
                "storage_uploaded",
                extra={
                    "upload_latency_ms": round(upload_latency_ms, 2),
                    "queue_depth": queue_depth,
                    "s3_key": s3_key,
                    "session_id": session_id,
                },
            )
            return result
