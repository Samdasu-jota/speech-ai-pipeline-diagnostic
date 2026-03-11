"""
FailureSimulator — injects fault conditions into the pipeline metrics
to exercise the DiagnosticsEngine and validate fault detection coverage.

Each scenario overrides specific MetricsRegistry gauges, causing pipeline
stages to behave as if a real fault is occurring. The diagnostic engine
then runs its normal detection loop and should fire the expected alerts
and generate root cause reports.

This mirrors fault injection testing in automotive diagnostics where
individual sensor signals are overridden to verify ECU fault detection.

Available scenarios:
  high_background_noise   — degrades audio SNR, causing STT WER to rise
  llm_rate_limit          — simulates LLM API 429 rate limiting
  stt_timeout             — simulates STT API timeout / high latency
  cpu_spike               — simulates high CPU utilisation
  cascading_failure       — combined STT degradation + LLM latency spike
  gradual_wer_drift       — slowly drifts WER upward over the scenario duration
  memory_pressure         — simulates high memory utilisation
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from enum import Enum
from typing import Optional

from monitoring.metrics_registry import MetricsRegistry

logger = logging.getLogger(__name__)


class FailureScenario(str, Enum):
    HIGH_BACKGROUND_NOISE = "high_background_noise"
    LLM_RATE_LIMIT = "llm_rate_limit"
    STT_TIMEOUT = "stt_timeout"
    CPU_SPIKE = "cpu_spike"
    CASCADING_FAILURE = "cascading_failure"
    GRADUAL_WER_DRIFT = "gradual_wer_drift"
    MEMORY_PRESSURE = "memory_pressure"


# Scenario parameter definitions
_SCENARIOS: dict[str, dict] = {
    FailureScenario.HIGH_BACKGROUND_NOISE: {
        "description": "High background noise degrading audio SNR and STT accuracy",
        "overrides": {
            "audio_snr_db": 5.0,
            "audio_noise_floor_dbfs": -20.0,
            "stt_word_error_rate": 0.28,
        },
    },
    FailureScenario.LLM_RATE_LIMIT: {
        "description": "LLM API rate limiting — >10% of requests returning 429",
        "overrides": {
            "llm_error_rate_429": 0.45,
            "llm_api_latency_p99_ms": 4500.0,
        },
    },
    FailureScenario.STT_TIMEOUT: {
        "description": "STT API timeouts causing high transcription latency",
        "overrides": {
            "stt_word_error_rate": 0.22,
            "pipeline_e2e_latency_p99_ms": 9000.0,
        },
    },
    FailureScenario.CPU_SPIKE: {
        "description": "CPU spike causing LLM latency degradation",
        "overrides": {
            "system_cpu_percent": 92.0,
            "llm_api_latency_p99_ms": 3800.0,
        },
    },
    FailureScenario.CASCADING_FAILURE: {
        "description": "Cascading failure — noisy audio → bad STT → LLM errors",
        "overrides": {
            "audio_snr_db": 4.5,
            "stt_word_error_rate": 0.31,
            "llm_api_latency_p99_ms": 3200.0,
            "pipeline_e2e_latency_p99_ms": 8500.0,
        },
    },
    FailureScenario.GRADUAL_WER_DRIFT: {
        "description": "Gradual WER drift — statistical anomaly detection scenario",
        "overrides": {},  # Applied incrementally in _gradual_drift_thread
    },
    FailureScenario.MEMORY_PRESSURE: {
        "description": "High memory utilisation approaching OOM threshold",
        "overrides": {
            "system_memory_percent": 93.0,
            "system_cpu_percent": 78.0,
        },
    },
}

# Healthy baseline values to restore on stop
_HEALTHY_BASELINES = {
    "audio_snr_db": 22.0,
    "audio_noise_floor_dbfs": -60.0,
    "stt_word_error_rate": 0.06,
    "llm_error_rate_429": 0.0,
    "llm_api_latency_p99_ms": 0.0,
    "pipeline_e2e_latency_p99_ms": 0.0,
    "system_cpu_percent": 30.0,
    "system_memory_percent": 40.0,
}


class FailureSimulator:
    """
    Injects fault conditions into the metrics registry.

    Usage:
        simulator = FailureSimulator()
        simulator.start("high_background_noise", duration_seconds=30)
        ...
        simulator.stop()
    """

    def __init__(self) -> None:
        self.registry = MetricsRegistry.instance()
        self._active_scenario: Optional[str] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def available_scenarios(self) -> list[dict]:
        return [
            {"id": k, "description": v["description"]}
            for k, v in _SCENARIOS.items()
        ]

    def start(self, scenario_id: str, duration_seconds: int = 30) -> str:
        if scenario_id not in _SCENARIOS:
            raise ValueError(
                f"Unknown scenario '{scenario_id}'. "
                f"Available: {list(_SCENARIOS.keys())}"
            )

        # Stop any currently running simulation first
        if self._active_scenario:
            self.stop()

        self._active_scenario = scenario_id
        self._stop_event.clear()
        scenario = _SCENARIOS[scenario_id]

        if scenario_id == FailureScenario.GRADUAL_WER_DRIFT:
            self._thread = threading.Thread(
                target=self._gradual_drift_thread,
                args=(duration_seconds,),
                daemon=True,
                name=f"Simulator-{scenario_id}",
            )
        else:
            self._thread = threading.Thread(
                target=self._fixed_override_thread,
                args=(scenario["overrides"], duration_seconds),
                daemon=True,
                name=f"Simulator-{scenario_id}",
            )

        self._thread.start()
        msg = f"Scenario '{scenario_id}' started for {duration_seconds}s: {scenario['description']}"
        logger.info(
            "failure_simulation_started",
            extra={"scenario": scenario_id, "duration_s": duration_seconds},
        )
        return msg

    def stop(self) -> None:
        if not self._active_scenario:
            return
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        self._restore_baselines()
        logger.info(
            "failure_simulation_stopped",
            extra={"scenario": self._active_scenario},
        )
        self._active_scenario = None

    # ------------------------------------------------------------------
    # Simulation threads
    # ------------------------------------------------------------------

    def _fixed_override_thread(
        self, overrides: dict[str, float], duration_seconds: int
    ) -> None:
        deadline = time.monotonic() + duration_seconds
        while not self._stop_event.is_set() and time.monotonic() < deadline:
            for metric, value in overrides.items():
                self.registry.set_metric(metric, value)
            self._stop_event.wait(timeout=1.0)
        self._restore_baselines()
        self._active_scenario = None

    def _gradual_drift_thread(self, duration_seconds: int) -> None:
        """Slowly increases WER from healthy to degraded over duration."""
        start_wer = 0.06
        target_wer = 0.30
        start_time = time.monotonic()
        deadline = start_time + duration_seconds

        while not self._stop_event.is_set() and time.monotonic() < deadline:
            elapsed = time.monotonic() - start_time
            progress = min(1.0, elapsed / duration_seconds)
            current_wer = start_wer + (target_wer - start_wer) * progress
            self.registry.set_metric("stt_word_error_rate", current_wer)
            self._stop_event.wait(timeout=2.0)

        self._restore_baselines()
        self._active_scenario = None

    def _restore_baselines(self) -> None:
        for metric, value in _HEALTHY_BASELINES.items():
            self.registry.set_metric(metric, value)
        logger.info("failure_simulation_metrics_restored")
