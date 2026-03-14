# Speech AI Pipeline Diagnostic System — Claude Code Guide

## Project Overview

Automated diagnostic system for a simulated speech AI pipeline. The simulated
pipeline mirrors the **Self English Tutor** app (`Self English Tutor2/`) —
same stages, same APIs, same failure modes. The focus is **diagnostics
engineering** — fault detection, root cause analysis, structured reporting,
and observability — mirroring Tesla Service Engineering.

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

# List all scenarios
curl http://localhost:8000/api/simulate/scenarios
```

### Frontend (local, without Docker)
```bash
cd frontend
npm install
npm run dev
```

## Real App Pipeline (Self English Tutor)

```
POST /audio/upload (mobile app)
    ↓ S3 upload
    ↓ Celery task dispatch (Redis broker)

Celery Worker — process_audio_task:
  Stage 1: PREPROCESSING
    WAV convert → normalize (-3dBFS) → spectral denoise
    → silero-vad (speech_ratio) → silence strip → chunk (≤600s)

  Stage 2: TRANSCRIPTION (OpenAI Whisper API)
    → confidence (0-1), word_count, language, cleaned_text

  Stage 3: FEEDBACK GENERATION (GPT-4o)
    → grammar_score, fluency_score, pronunciation_score, overall_score (0-10)
    → mistakes, vocabulary_suggestions, natural_version
```

## Diagnostic System Architecture

```
backend/
├── main.py                     FastAPI entry point + lifespan startup
├── pipeline/                   Simulated stages (mirrors real tutor pipeline)
│   ├── audio_stage.py          Preprocessing (SNR, noise floor, speech_ratio)
│   ├── stt_stage.py            Transcription (mock | Whisper) — confidence, WER
│   ├── storage_stage.py        S3 upload + Celery queue simulation
│   ├── feedback_stage.py       Feedback generation (mock | GPT-4o | Claude)
│   └── pipeline_runner.py      Orchestrates preprocessing→transcription→storage→feedback
├── monitoring/
│   ├── metrics_registry.py     Prometheus singleton — owns all instruments
│   ├── stage_monitor.py        Context manager: latency + error telemetry
│   └── system_monitor.py       Background thread: CPU/memory polling
├── diagnostics/
│   ├── rules.py                12 threshold rules with DTC-style codes
│   ├── anomaly_detector.py     Z-score rolling window (300-sample default, 7 metrics)
│   ├── root_cause_analyzer.py  Causal graph: 10 CausalRule mappings
│   ├── report_generator.py     DiagnosticReport builder + stage health
│   └── engine.py               Core polling loop (every 10s default)
├── api/
│   ├── routes.py               REST + WebSocket route definitions
│   ├── websocket.py            ConnectionManager + broadcast helpers
│   └── schemas.py              Pydantic request/response models
├── simulation/
│   └── failure_simulator.py    8 fault injection scenarios
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
Rules use codes modelled on OBD-II diagnostic trouble codes:

| Prefix | Stage | Examples |
|---|---|---|
| `AUD-xxx` | Preprocessing | AUD-001 (low SNR), AUD-002 (near-silent) |
| `STT-xxx` | Transcription | STT-001 (high WER), STT-003 (low Whisper confidence) |
| `FBK-xxx` | Feedback | FBK-001 (latency spike), FBK-002 (rate limit), FBK-003 (poor quality) |
| `SYS-xxx` | System/infra | SYS-001 (CPU), SYS-002 (memory), SYS-003 (E2E timeout) |

### Root cause analysis
`RootCauseAnalyzer` holds `CausalRule` objects. Each matches a `frozenset`
of required alert IDs (must all be present) plus optional IDs that boost
confidence. The highest-confidence matching rule wins. See
[backend/diagnostics/root_cause_analyzer.py](backend/diagnostics/root_cause_analyzer.py).

## Key Metrics Tracked

| Metric | Stage | Baseline | Rule |
|---|---|---|---|
| `audio_snr_db` | Preprocessing | 22 dB | AUD-001 |
| `audio_speech_ratio` | Preprocessing | 0.82 | AUD-002, STT-004 |
| `stt_word_error_rate` | Transcription | 0.06 | STT-001, STT-002 |
| `stt_confidence_score` | Transcription | 0.88 | STT-003 |
| `stt_word_count` | Transcription | 45 | — |
| `feedback_api_latency_p99_ms` | Feedback | 1800 ms | FBK-001 |
| `feedback_error_rate_429` | Feedback | 0.0 | FBK-002 |
| `feedback_grammar_score` | Feedback | 7.5/10 | — |
| `feedback_overall_score` | Feedback | 7.4/10 | FBK-003 |
| `celery_queue_depth` | Storage/Queue | 0 | — |
| `system_cpu_percent` | System | 30% | SYS-001 |
| `system_memory_percent` | System | 40% | SYS-002 |
| `pipeline_e2e_latency_p99_ms` | Pipeline | 2000 ms | SYS-003 |

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `PIPELINE_STT_BACKEND` | `mock` | `mock` / `whisper` / `deepgram` |
| `PIPELINE_LLM_BACKEND` | `mock` | `mock` / `openai` / `claude` |
| `DIAG_POLL_INTERVAL` | `10` | Diagnostics engine poll interval (seconds) |
| `DIAG_ANOMALY_WINDOW` | `300` | Z-score rolling window size (samples) |
| `DIAG_ZSCORE_THRESHOLD` | `3.0` | Standard deviations to trigger anomaly alert |
| `OPENAI_API_KEY` | — | Required for `PIPELINE_LLM_BACKEND=openai` (GPT-4o) |
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
| `high_background_noise` | SNR→5dB, WER→28%, confidence→0.52 | AUD-001, STT-001, STT-003 |
| `feedback_rate_limit` | 429 rate→45%, FBK P99→5500ms | FBK-002 |
| `stt_timeout` | WER→22%, confidence→0.61, E2E→9s | STT-001, STT-003, SYS-003 |
| `cpu_spike` | CPU→92%, FBK P99→5200ms | SYS-001, FBK-001 |
| `cascading_failure` | SNR→4.5dB, WER→31%, confidence→0.48, score→4.2 | AUD-001, STT-001, STT-003, FBK-003 |
| `gradual_quality_drift` | Confidence drifts 0.88→0.45 | ANOMALY_STT_CONFIDENCE_SCORE (Z-score) |
| `memory_pressure` | Memory→93% | SYS-002 |
| `celery_queue_backup` | queue_depth→25, E2E→12s | SYS-003 |

## Adding a New Diagnostic Rule

1. Add a `Rule(...)` entry to `RULES` in [backend/diagnostics/rules.py](backend/diagnostics/rules.py)
2. Add a `CausalRule(...)` to `_CAUSAL_RULES` in [backend/diagnostics/root_cause_analyzer.py](backend/diagnostics/root_cause_analyzer.py) if the new rule participates in a root cause pattern
3. Add a test case in [backend/tests/test_rules.py](backend/tests/test_rules.py)
4. Add a Grafana panel for the new metric in `observability/grafana/dashboards/`

## Adding a New Failure Scenario

1. Add an entry to `_SCENARIOS` dict in [backend/simulation/failure_simulator.py](backend/simulation/failure_simulator.py)
2. Add a button to `frontend/src/components/SimulationControls.tsx`
3. Document expected DTC codes in [docs/failure_scenarios.md](docs/failure_scenarios.md)
