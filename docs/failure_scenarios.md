# Failure Scenarios

Aligned with the **Self English Tutor** app pipeline:
`POST /audio/upload → S3 → Celery: Preprocessing → Transcription → Feedback (GPT-4o)`

## Scenario Reference

| Scenario ID | Description | Injected Metrics | Expected DTC Codes | Expected RCA |
|---|---|---|---|---|
| `high_background_noise` | High background noise degrading audio SNR and Whisper confidence | SNR→5dB, WER→28%, confidence→0.52 | AUD-001, STT-001, STT-003 | RCA-01 or RCA-08 |
| `feedback_rate_limit` | GPT-4o API rate limiting — >10% of requests returning 429 | feedback_error_rate_429→45%, feedback_p99→5500ms | FBK-002 | RCA-03 |
| `stt_timeout` | Whisper API timeouts causing high latency and low confidence | WER→22%, confidence→0.61, E2E→9s | STT-001, STT-003, SYS-003 | RCA-06 |
| `cpu_spike` | CPU spike throttling Celery workers and GPT-4o calls | CPU→92%, feedback_p99→5200ms | SYS-001, FBK-001 | RCA-02 |
| `cascading_failure` | Noisy audio → bad Whisper transcript → poor GPT-4o feedback | SNR→4.5dB, WER→31%, confidence→0.48, overall_score→4.2 | AUD-001, STT-001, STT-003, FBK-003 | RCA-08 + RCA-09 |
| `gradual_quality_drift` | Whisper confidence drifts 0.88→0.45 over scenario duration | confidence and WER drift incrementally | ANOMALY_STT_CONFIDENCE_SCORE | Z-score anomaly detector |
| `memory_pressure` | High memory approaching OOM — pydub/torch VAD buffers leaking | memory→93%, CPU→78% | SYS-002 | RCA-07 |
| `celery_queue_backup` | Celery task queue backup — jobs accumulating faster than workers process | celery_queue_depth→25, E2E→12s | SYS-003 | RCA-06 |

---

## DTC Code Reference

| DTC Code | Rule ID | Stage | Threshold | Severity |
|---|---|---|---|---|
| AUD-001 | LOW_AUDIO_SNR | Preprocessing | SNR < 10 dB | WARN |
| AUD-002 | AUD_NEAR_SILENT | Preprocessing | speech_ratio < 0.20 | CRITICAL |
| STT-001 | STT_HIGH_WER | Transcription | WER > 20% | CRITICAL |
| STT-002 | STT_LOW_CONFIDENCE | Transcription | WER > 15% (early warning) | WARN |
| STT-003 | STT_LOW_CONFIDENCE_SCORE | Transcription | Whisper confidence < 0.70 | WARN |
| STT-004 | STT_LOW_SPEECH_RATIO | Transcription | speech_ratio < 0.40 | WARN |
| FBK-001 | FBK_LATENCY_SPIKE | Feedback | GPT-4o P99 > 5000 ms | WARN |
| FBK-002 | FBK_RATE_LIMIT | Feedback | 429 error rate > 10% | CRITICAL |
| FBK-003 | FBK_POOR_QUALITY | Feedback | overall_score < 5.0/10 | WARN |
| SYS-001 | HIGH_CPU | System | CPU > 85% | WARN |
| SYS-002 | HIGH_MEMORY | System | Memory > 90% | CRITICAL |
| SYS-003 | PIPELINE_TIMEOUT | Pipeline | E2E P99 > 8 s | CRITICAL |

---

## Root Cause Rules Reference

| RCA Rule | Required Alerts | Probable Cause | Confidence |
|---|---|---|---|
| RCA-01 | STT_HIGH_WER + LOW_AUDIO_SNR | Microphone noise degrading transcription | 0.88+ |
| RCA-02 | FBK_LATENCY_SPIKE + HIGH_CPU | Resource contention throttling Celery/GPT-4o | 0.82+ |
| RCA-03 | FBK_RATE_LIMIT | GPT-4o rate limit quota exceeded | 0.95 |
| RCA-04 | FBK_LATENCY_SPIKE | External GPT-4o API latency (provider-side) | 0.72+ |
| RCA-05 | STT_HIGH_WER + FBK_LATENCY_SPIKE | Cascading: bad transcription → GPT-4o errors | 0.78+ |
| RCA-06 | PIPELINE_TIMEOUT | Cumulative Celery task latency timeout | 0.70+ |
| RCA-07 | HIGH_MEMORY | Memory pressure from VAD/audio buffers | 0.88+ |
| RCA-08 | STT_HIGH_WER + STT_LOW_CONFIDENCE_SCORE + LOW_AUDIO_SNR | Noise degrading Whisper confidence AND accuracy | 0.93+ |
| RCA-09 | FBK_POOR_QUALITY + STT_LOW_CONFIDENCE_SCORE | Low confidence causing garbage-in-garbage-out to GPT-4o | 0.88+ |
| RCA-10 | STT_LOW_SPEECH_RATIO | VAD/silence detection issue — insufficient speech in audio | 0.80+ |

---

## Trigger Commands

```bash
# Start a scenario
curl -X POST http://localhost:8000/api/simulate/high_background_noise \
     -H "Content-Type: application/json" \
     -d '{"duration_seconds": 45}'

# Stop active scenario
curl -X DELETE http://localhost:8000/api/simulate/stop

# List available scenarios
curl http://localhost:8000/api/simulate/scenarios
```
