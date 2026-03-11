# Speech AI Pipeline Diagnostic System

An automated diagnostic system that monitors a simulated speech AI pipeline,
detects failures across pipeline stages, performs root cause analysis, and
generates structured diagnostic reports — modelled on the engineering principles
used in automotive and embedded diagnostic systems.

## Architecture

```
[Mic Input] → [Audio] → [STT] → [NLP] → [LLM] → [Output]
                   ↓ telemetry (Prometheus)
             Diagnostics Engine
              ├── Rules Evaluator (threshold + DTC-style codes)
              ├── Z-score Anomaly Detector (rolling window)
              ├── Root Cause Analyzer (causal graph)
              └── Report Generator (structured JSON/WebSocket)
                   ↓
        FastAPI + WebSocket → React Dashboard
        Prometheus + Grafana (5 dashboards)
```

## Quick Start

```bash
cp .env.example .env
# optionally add API keys for real STT/LLM backends

docker-compose up --build
```

| Service | URL |
|---|---|
| React Dashboard | http://localhost:5173 |
| FastAPI (docs) | http://localhost:8000/docs |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3001 (admin/admin) |

## Running Tests

```bash
cd backend
pip install -r requirements.txt
pytest tests/ -v --tb=short
```

## Failure Simulation Demo

Trigger a fault via the dashboard UI or directly via the API:

```bash
# Inject high background noise
curl -X POST http://localhost:8000/api/simulate/high_background_noise \
     -H "Content-Type: application/json" \
     -d '{"duration_seconds": 45}'

# Watch the diagnostics engine fire STT-001 + AUD-001 within 10s
# Root cause: "Microphone noise degrading transcription accuracy"

# Stop simulation
curl -X DELETE http://localhost:8000/api/simulate/stop
```

Available scenarios: `high_background_noise`, `llm_rate_limit`, `stt_timeout`,
`cpu_spike`, `cascading_failure`, `gradual_wer_drift`, `memory_pressure`

## Key Components

| Module | Purpose |
|---|---|
| `backend/diagnostics/engine.py` | Core diagnostic polling loop |
| `backend/diagnostics/rules.py` | DTC-style threshold rules (8 rules) |
| `backend/diagnostics/anomaly_detector.py` | Z-score statistical detection |
| `backend/diagnostics/root_cause_analyzer.py` | Causal graph RCA (7 causal rules) |
| `backend/monitoring/metrics_registry.py` | Prometheus instruments singleton |
| `backend/simulation/failure_simulator.py` | Fault injection framework |

## Example Diagnostic Report

```json
{
  "pipeline_status": "CRITICAL",
  "root_cause_analysis": {
    "probable_cause": "Microphone noise degrading transcription accuracy",
    "confidence": 0.91,
    "evidence": ["AUD-001: Audio SNR dropped from 22dB to 5.0dB", "STT-001: WER increased from 6% to 28%"],
    "suggested_fix": "Enable noise filtering; check microphone placement"
  },
  "stage_health": {
    "audio_capture": "DEGRADED",
    "speech_to_text": "CRITICAL",
    "llm": "HEALTHY"
  }
}
```

## Tech Stack

Python 3.12 · FastAPI · Prometheus · Grafana · React · TypeScript · Docker
