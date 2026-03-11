"""
FastAPI application entry point.

Starts:
  - Prometheus metrics endpoint at /metrics
  - REST API routes
  - WebSocket live-stream at /ws/diagnostics
  - DiagnosticsEngine background task
  - SystemMonitor background thread
  - PipelineRunner continuous loop (processes one request every 2s)
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

# Configure structured JSON-like logging
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup / shutdown lifecycle."""
    from diagnostics.engine import DiagnosticsEngine
    from monitoring.system_monitor import SystemMonitor
    from pipeline.pipeline_runner import PipelineRunner
    from simulation.failure_simulator import FailureSimulator
    from api.routes import inject_dependencies
    from api.websocket import broadcast_report

    # Instantiate singletons
    engine = DiagnosticsEngine(
        poll_interval_seconds=int(os.getenv("DIAG_POLL_INTERVAL", "10")),
        anomaly_window=int(os.getenv("DIAG_ANOMALY_WINDOW", "300")),
        zscore_threshold=float(os.getenv("DIAG_ZSCORE_THRESHOLD", "3.0")),
    )
    engine.set_broadcast_callback(broadcast_report)

    runner = PipelineRunner()
    simulator = FailureSimulator()
    sys_monitor = SystemMonitor(interval=5.0)

    inject_dependencies(runner, engine, simulator)

    # Start background services
    sys_monitor.start()
    diag_task = asyncio.create_task(engine.run(), name="DiagnosticsEngine")
    pipeline_task = asyncio.create_task(_pipeline_loop(runner), name="PipelineLoop")

    logger.info("Speech AI Diagnostic System started")
    yield

    # Shutdown
    engine.stop()
    diag_task.cancel()
    pipeline_task.cancel()
    sys_monitor.stop()
    logger.info("Speech AI Diagnostic System stopped")


async def _pipeline_loop(runner) -> None:  # type: ignore[type-arg]
    """Continuously runs pipeline requests to generate live telemetry."""
    while True:
        try:
            await runner.run_async()
        except Exception:
            pass
        await asyncio.sleep(2.0)


app = FastAPI(
    title="Speech AI Pipeline Diagnostic System",
    description=(
        "Automated diagnostic system that monitors a speech AI pipeline, "
        "detects failures, performs root cause analysis, and generates "
        "structured diagnostic reports."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from api.routes import router  # noqa: E402
app.include_router(router)
