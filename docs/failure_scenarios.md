# Failure Scenarios

Each scenario tests a specific fault pattern and validates that the diagnostic
engine correctly detects, correlates, and reports it.

| Scenario | Injected Metrics | Expected DTC Codes | Expected RCA Rule |
|---|---|---|---|
| `high_background_noise` | SNR→5dB, WER→28% | AUD-001, STT-001 | RCA-01 |
| `llm_rate_limit` | 429 rate→45% | LLM-002 | RCA-03 |
| `stt_timeout` | WER→22%, E2E→9s | STT-001, SYS-003 | RCA-06 |
| `cpu_spike` | CPU→92%, LLM P99→3.8s | SYS-001, LLM-001 | RCA-02 |
| `cascading_failure` | SNR→4.5dB, WER→31%, E2E→8.5s | AUD-001, STT-001, SYS-003 | RCA-05 |
| `gradual_wer_drift` | WER drifts 6%→30% over N seconds | ANOMALY_STT_* (Z-score) | RCA-01 |
| `memory_pressure` | Memory→93% | SYS-002 | RCA-07 |

## DTC Code Reference

| Code | Stage | Condition | Severity |
|---|---|---|---|
| AUD-001 | Audio Capture | SNR < 10 dB | WARN |
| STT-001 | Speech-to-Text | WER > 20% | CRITICAL |
| STT-002 | Speech-to-Text | WER > 15% (proxy for confidence) | WARN |
| LLM-001 | LLM | P99 latency > 3000 ms | WARN |
| LLM-002 | LLM | 429 error rate > 10% | CRITICAL |
| SYS-001 | System | CPU > 85% | WARN |
| SYS-002 | System | Memory > 90% | CRITICAL |
| SYS-003 | Pipeline | E2E P99 > 8000 ms | CRITICAL |
