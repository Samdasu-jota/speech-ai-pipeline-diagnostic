"""
FastAPI route definitions.

Endpoints:
  GET  /health                         — liveness probe
  GET  /metrics                        — Prometheus exposition
  POST /api/pipeline/run               — trigger a single pipeline request
  GET  /api/pipeline/status            — current stage health + active alerts
  GET  /api/diagnostics/reports        — recent diagnostic report history
  GET  /api/diagnostics/alerts         — currently active alerts
  POST /api/simulate/{scenario}        — inject a failure scenario
  DELETE /api/simulate/stop            — cancel active simulation
  WS   /ws/diagnostics                 — WebSocket live stream
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, UTC
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import Response

from api.schemas import (
    PipelineRunRequest,
    PipelineRunResponse,
    MetricsSnapshotResponse,
    SimulateRequest,
    SimulateResponse,
    AlertItem,
)
from api.websocket import manager
from monitoring.metrics_registry import MetricsRegistry

logger = logging.getLogger(__name__)
router = APIRouter()

# These are injected by main.py after startup
_pipeline_runner = None
_diagnostics_engine = None
_failure_simulator = None


def inject_dependencies(runner, engine, simulator) -> None:  # type: ignore[type-arg]
    global _pipeline_runner, _diagnostics_engine, _failure_simulator
    _pipeline_runner = runner
    _diagnostics_engine = engine
    _failure_simulator = simulator


# ──────────────────────────────────────────────────────────────────────────────
# Health & Metrics
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "timestamp": datetime.now(UTC).isoformat()}


@router.get("/metrics")
async def metrics() -> Response:
    registry = MetricsRegistry.instance()
    data, content_type = registry.exposition_data()
    return Response(content=data, media_type=content_type)


# ──────────────────────────────────────────────────────────────────────────────
# Pipeline
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/api/pipeline/run", response_model=PipelineRunResponse)
async def run_pipeline(body: PipelineRunRequest) -> PipelineRunResponse:
    if _pipeline_runner is None:
        raise HTTPException(status_code=503, detail="Pipeline runner not initialised")
    result = await _pipeline_runner.run_async(session_id=body.session_id)
    return PipelineRunResponse(
        session_id=result.session_id,
        request_id=result.request_id,
        success=result.success,
        corrected_text=result.response.corrected_text if result.response else None,
        original_transcript=result.response.original_transcript if result.response else None,
        e2e_latency_ms=round(result.e2e_latency_ms, 2),
        stage_latencies={k: round(v, 2) for k, v in result.stage_latencies.items()},
        failed_stage=result.failed_stage,
        error_message=result.error_message,
    )


@router.get("/api/pipeline/status")
async def pipeline_status() -> dict[str, Any]:
    if _diagnostics_engine is None:
        return {"active_alerts": [], "metrics": {}}
    return {
        "active_alerts": _diagnostics_engine.get_active_alerts(),
        "metrics": MetricsRegistry.instance().snapshot(),
        "timestamp": datetime.now(UTC).isoformat(),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Diagnostics
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/api/diagnostics/reports")
async def get_reports(limit: int = 20) -> dict[str, Any]:
    if _diagnostics_engine is None:
        return {"reports": []}
    history = _diagnostics_engine.get_report_history()
    return {"reports": history[-limit:], "total": len(history)}


@router.get("/api/diagnostics/alerts")
async def get_alerts() -> dict[str, Any]:
    if _diagnostics_engine is None:
        return {"alerts": []}
    return {
        "alerts": _diagnostics_engine.get_active_alerts(),
        "timestamp": datetime.now(UTC).isoformat(),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Failure Simulation
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/api/simulate/{scenario}", response_model=SimulateResponse)
async def simulate_failure(scenario: str, body: SimulateRequest) -> SimulateResponse:
    if _failure_simulator is None:
        raise HTTPException(status_code=503, detail="Simulator not initialised")
    try:
        msg = _failure_simulator.start(scenario, duration_seconds=body.duration_seconds or 30)
        return SimulateResponse(
            scenario=scenario,
            status="started",
            message=msg,
            duration_seconds=body.duration_seconds or 30,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/api/simulate/stop")
async def stop_simulation() -> dict[str, str]:
    if _failure_simulator is None:
        raise HTTPException(status_code=503, detail="Simulator not initialised")
    _failure_simulator.stop()
    return {"status": "stopped"}


@router.get("/api/simulate/scenarios")
async def list_scenarios() -> dict[str, Any]:
    if _failure_simulator is None:
        return {"scenarios": []}
    return {"scenarios": _failure_simulator.available_scenarios()}


# ──────────────────────────────────────────────────────────────────────────────
# WebSocket
# ──────────────────────────────────────────────────────────────────────────────

@router.websocket("/ws/diagnostics")
async def websocket_diagnostics(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            # Keep connection alive; server-push only
            await asyncio.sleep(30)
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)
