# Speech AI Pipeline Diagnostic System — Claude Code Guide

## Project Overview

Automated diagnostic system for a simulated speech AI pipeline. The focus is
**diagnostics engineering** — fault detection, root cause analysis, structured
reporting, and observability — not the AI features themselves. Built to mirror
the engineering thinking of Tesla Service Engineering.

## Commands

### Run the full stack
```bash
cp .env.example .env          # first time only
docker-compose up --build
```

### Run backend only (no Docker)
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Run tests
```bash
cd backend
pytest tests/ -v --tb=short
pytest tests/test_rules.py -v               # unit: rules only
pytest tests/test_rca.py -v                 # unit: root cause analyzer
pytest tests/test_anomaly_detector.py -v    # unit: Z-score detector
pytest tests/test_diagnostics_engine.py -v  # integration: engine loop
pytest tests/test_pipeline_runner.py -v     # integration: full pipeline
```

### Trigger a failure scenario (demo)
```bash
curl -X POST http://localhost:8000/api/simulate/high_background_noise \
     -H "Content-Type: application/json" \
     -d '{"duration_seconds": 45}'

# Stop it
curl -X DELETE http://localhost:8000/api/simulate/stop
```

### Frontend (local, without Docker)
```bash
cd frontend
npm install
npm run dev
```

## Architecture

```
backend/
├── main.py                     FastAPI entry point + lifespan startup
├── pipeline/                   Simulated speech AI pipeline stages
│   ├── audio_stage.py          Microphone capture (SNR, noise floor)
│   ├── stt_stage.py            Speech-to-text (mock | Whisper | Deepgram)
│   ├── nlp_stage.py            Language processing + tokenisation
│   ├── llm_stage.py            Grammar correction (mock | Claude | OpenAI)
│   ├── output_stage.py         Response delivery
│   └── pipeline_runner.py      Orchestrates full audio→output pipeline
├── monitoring/
│   ├── metrics_registry.py     Prometheus singleton — owns all instruments
│   ├── stage_monitor.py        Context manager: latency + error telemetry
│   └── system_monitor.py       Background thread: CPU/memory polling
├── diagnostics/
│   ├── rules.py                8 threshold rules with DTC-style codes
│   ├── anomaly_detector.py     Z-score rolling window (300-sample default)
│   ├── root_cause_analyzer.py  Causal graph: 7 CausalRule mappings
│   ├── report_generator.py     DiagnosticReport builder + stage health
│   └── engine.py               Core polling loop (every 10s default)
├── api/
│   ├── routes.py               REST + WebSocket route definitions
│   ├── websocket.py            ConnectionManager + broadcast helpers
│   └── schemas.py              Pydantic request/response models
├── simulation/
│   └── failure_simulator.py    7 fault injection scenarios
└── tests/                      pytest suite (unit + integration)

frontend/src/
├── App.tsx                     Main dashboard layout
├── hooks/usePipelineAlerts.ts  WebSocket hook with auto-reconnect
└── components/
    ├── PipelineHealthGrid.tsx   Stage health colour grid
    ├── AlertFeed.tsx            Live DTC alert list
    ├── DiagnosticReportCard.tsx Expandable report with RCA detail
    └── SimulationControls.tsx   Fault injection trigger UI

observability/
├── prometheus/prometheus.yml   Scrape config (backend:8000/metrics)
└── grafana/
    ├── datasources/             Prometheus datasource provisioning
    └── dashboards/              Auto-provisioned Grafana dashboards
```

## Key Design Patterns

### MetricsRegistry singleton
All Prometheus instruments live in `MetricsRegistry.instance()`. Never create
instruments elsewhere — this prevents duplicate registration errors across the
async app and background threads.

### StageMonitor context manager
Wrap every stage operation in `StageMonitor.track()`. It records latency,
catches + classifies exceptions, and emits structured JSON log events with
`session_id` + `request_id` correlation IDs automatically.

```python
with self.monitor.track("transcribe", session_id=sid, request_id=rid):
    result = call_api(...)
```

### Failure injection via MetricsRegistry
The `FailureSimulator` overrides gauge values in `MetricsRegistry`. Pipeline
stages read these overrides on each run, so injected faults are reflected in
live telemetry without any special mocking. The diagnostics engine sees the
same metric values it would in a real fault.

### DTC-style fault codes
Rules use codes like `STT-001`, `AUD-001`, `LLM-002` modelled on OBD-II
diagnostic trouble codes. Each code has: description, severity, metric
condition, baseline value. See `backend/diagnostics/rules.py`.

### Root cause analysis
`RootCauseAnalyzer` holds `CausalRule` objects. Each matches a `frozenset`
of required alert IDs (must all be present) plus optional IDs that boost
confidence. The highest-confidence matching rule wins. See
`backend/diagnostics/root_cause_analyzer.py`.

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `PIPELINE_STT_BACKEND` | `mock` | `mock` / `whisper` / `deepgram` |
| `PIPELINE_LLM_BACKEND` | `mock` | `mock` / `claude` / `openai` |
| `DIAG_POLL_INTERVAL` | `10` | Diagnostics engine poll interval (seconds) |
| `DIAG_ANOMALY_WINDOW` | `300` | Z-score rolling window size (samples) |
| `DIAG_ZSCORE_THRESHOLD` | `3.0` | Standard deviations to trigger anomaly alert |
| `ANTHROPIC_API_KEY` | — | Required for `PIPELINE_LLM_BACKEND=claude` |
| `DEEPGRAM_API_KEY` | — | Required for `PIPELINE_STT_BACKEND=deepgram` |

## Service URLs

| Service | URL | Notes |
|---|---|---|
| React Dashboard | http://localhost:5173 | Live alerts + simulation controls |
| FastAPI docs | http://localhost:8000/docs | Interactive API explorer |
| Prometheus | http://localhost:9090 | Raw metric queries |
| Grafana | http://localhost:3001 | admin / admin |

## Failure Scenarios

| Scenario ID | Injected Fault | Expected DTC Codes |
|---|---|---|
| `high_background_noise` | SNR→5dB, WER→28% | AUD-001, STT-001 |
| `llm_rate_limit` | 429 rate→45% | LLM-002 |
| `stt_timeout` | WER→22%, E2E→9s | STT-001, SYS-003 |
| `cpu_spike` | CPU→92%, LLM P99→3.8s | SYS-001, LLM-001 |
| `cascading_failure` | SNR→4.5dB, WER→31% | AUD-001, STT-001, SYS-003 |
| `gradual_wer_drift` | WER drifts 6%→30% | ANOMALY_STT_* (Z-score) |
| `memory_pressure` | Memory→93% | SYS-002 |

## Adding a New Diagnostic Rule

1. Add a `Rule(...)` entry to `RULES` in `backend/diagnostics/rules.py`
2. Add a `CausalRule(...)` to `_CAUSAL_RULES` in `root_cause_analyzer.py` if
   the new rule participates in a root cause pattern
3. Add a test case in `backend/tests/test_rules.py`
4. Add a Grafana panel for the new metric in `observability/grafana/dashboards/`

## Adding a New Failure Scenario

1. Add an entry to `_SCENARIOS` dict in `backend/simulation/failure_simulator.py`
2. Add a button to `frontend/src/components/SimulationControls.tsx`
3. Document expected DTC codes in `docs/failure_scenarios.md`
