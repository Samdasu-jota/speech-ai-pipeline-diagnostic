"""
Pydantic schemas for FastAPI request/response models.
"""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel


class PipelineRunRequest(BaseModel):
    session_id: Optional[str] = None


class PipelineRunResponse(BaseModel):
    session_id: str
    request_id: str
    success: bool
    corrected_text: Optional[str] = None
    original_transcript: Optional[str] = None
    e2e_latency_ms: float
    stage_latencies: dict[str, float]
    failed_stage: Optional[str] = None
    error_message: Optional[str] = None


class AlertItem(BaseModel):
    rule_id: str
    dtc_code: str
    severity: str
    message: str
    current_value: float


class SimulateRequest(BaseModel):
    duration_seconds: Optional[int] = 30


class SimulateResponse(BaseModel):
    scenario: str
    status: str
    message: str
    duration_seconds: int


class MetricsSnapshotResponse(BaseModel):
    metrics: dict[str, Any]
    active_alerts: list[AlertItem]
    timestamp: str
