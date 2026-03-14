"""
Preprocessing Stage — simulates audio capture and preprocessing.

Mirrors the Self English Tutor app's PREPROCESSING Celery stage:
  WAV conversion → amplitude normalisation → spectral noise reduction
  → VAD (silero-vad) → silence stripping → chunking for Whisper

In production this would interface with PyAudio / pydub / silero-vad.
Here it generates synthetic audio characteristics (SNR, noise floor,
speech_ratio) that the FailureSimulator can override to exercise the
diagnostics engine without real hardware.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass

from monitoring.metrics_registry import MetricsRegistry
from monitoring.stage_monitor import StageMonitor

logger = logging.getLogger(__name__)

# Default healthy audio parameters
_HEALTHY_SNR_DB = 22.0
_HEALTHY_NOISE_FLOOR_DBFS = -60.0
_HEALTHY_LATENCY_MS_MEAN = 12.0
_HEALTHY_SPEECH_RATIO = 0.82   # 82% of audio is speech (after VAD)


@dataclass
class AudioFrame:
    snr_db: float
    noise_floor_dbfs: float
    speech_ratio: float          # fraction of audio identified as speech by VAD
    duration_ms: float
    sample_rate: int = 16000
    channels: int = 1
    raw_bytes: bytes = b""


class AudioStage:
    """
    Simulates audio capture and preprocessing.

    Reads override values from MetricsRegistry (set by FailureSimulator)
    so that fault injection scenarios are reflected in downstream stages.
    """

    def __init__(self) -> None:
        self.monitor = StageMonitor("audio")
        self.registry = MetricsRegistry.instance()

    def capture(
        self,
        duration_ms: float = 1000.0,
        session_id: str = "-",
        request_id: str = "-",
    ) -> AudioFrame:
        with self.monitor.track("capture", session_id=session_id, request_id=request_id):
            latency_ms = _HEALTHY_LATENCY_MS_MEAN + random.gauss(0, 2)
            time.sleep(latency_ms / 1000)

            # Allow failure simulator to override SNR and speech_ratio
            snap = self.registry.snapshot()
            snr = snap.get("audio_snr_db", _HEALTHY_SNR_DB)
            noise_floor = snap.get("audio_noise_floor_dbfs", _HEALTHY_NOISE_FLOOR_DBFS)
            speech_ratio = snap.get("audio_speech_ratio", _HEALTHY_SPEECH_RATIO)

            # Add small random jitter to make metrics look realistic
            snr += random.gauss(0, 0.5)
            noise_floor += random.gauss(0, 1.0)
            # speech_ratio is inversely correlated with noise: louder noise → less clean speech detected
            noise_penalty = max(0.0, (_HEALTHY_SNR_DB - snr) * 0.01)
            speech_ratio = max(0.05, min(1.0, speech_ratio - noise_penalty + random.gauss(0, 0.01)))

            self.registry.set_metric("audio_snr_db", snr)
            self.registry.set_metric("audio_noise_floor_dbfs", noise_floor)
            self.registry.set_metric("audio_speech_ratio", speech_ratio)
            self.registry.audio_capture_latency_ms.observe(latency_ms)

            frame = AudioFrame(
                snr_db=snr,
                noise_floor_dbfs=noise_floor,
                speech_ratio=speech_ratio,
                duration_ms=duration_ms,
            )
            logger.debug(
                "audio_frame_captured",
                extra={
                    "snr_db": round(snr, 2),
                    "noise_floor_dbfs": round(noise_floor, 2),
                    "speech_ratio": round(speech_ratio, 3),
                    "session_id": session_id,
                },
            )
            return frame
