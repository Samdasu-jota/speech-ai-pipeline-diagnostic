/**
 * SimulationControls — UI for triggering failure scenarios.
 *
 * POSTs to /api/simulate/{scenario} and displays the active scenario status.
 * This enables live demos: "watch the diagnostic engine detect this fault."
 */

import React, { useState } from "react";

const SCENARIOS = [
  {
    id: "high_background_noise",
    label: "High Background Noise",
    description: "Degrades audio SNR → STT WER rises to 28%",
    color: "#f59e0b",
  },
  {
    id: "llm_rate_limit",
    label: "LLM Rate Limit",
    description: "45% of LLM requests return 429",
    color: "#ef4444",
  },
  {
    id: "stt_timeout",
    label: "STT Timeout",
    description: "STT API timeouts → pipeline latency > 8s",
    color: "#ef4444",
  },
  {
    id: "cpu_spike",
    label: "CPU Spike",
    description: "CPU > 92% → LLM latency degrades",
    color: "#f59e0b",
  },
  {
    id: "cascading_failure",
    label: "Cascading Failure",
    description: "Noisy audio → bad STT → LLM errors",
    color: "#dc2626",
  },
  {
    id: "gradual_wer_drift",
    label: "Gradual WER Drift",
    description: "Slow WER increase — tests anomaly detector",
    color: "#8b5cf6",
  },
  {
    id: "memory_pressure",
    label: "Memory Pressure",
    description: "Memory > 93% — OOM risk",
    color: "#ef4444",
  },
];

export function SimulationControls() {
  const [active, setActive] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("");
  const [loading, setLoading] = useState(false);

  const trigger = async (scenarioId: string) => {
    setLoading(true);
    try {
      const res = await fetch(`/api/simulate/${scenarioId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ duration_seconds: 45 }),
      });
      const data = await res.json();
      setActive(scenarioId);
      setStatus(data.message || "Scenario started");
    } catch {
      setStatus("Failed to start scenario");
    } finally {
      setLoading(false);
    }
  };

  const stopSimulation = async () => {
    setLoading(true);
    try {
      await fetch("/api/simulate/stop", { method: "DELETE" });
      setActive(null);
      setStatus("Simulation stopped — metrics restoring to baseline");
    } catch {
      setStatus("Failed to stop simulation");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <h2 style={{ fontSize: 14, fontWeight: 600, color: "#94a3b8", letterSpacing: 1, textTransform: "uppercase" }}>
          Fault Injection
        </h2>
        {active && (
          <button
            onClick={stopSimulation}
            disabled={loading}
            style={{
              background: "#7f1d1d",
              color: "#fca5a5",
              border: "1px solid #ef4444",
              borderRadius: 6,
              padding: "4px 12px",
              fontSize: 11,
              cursor: "pointer",
            }}
          >
            Stop Simulation
          </button>
        )}
      </div>

      {status && (
        <div style={{ fontSize: 11, color: "#86efac", background: "#14532d22", padding: "6px 10px", borderRadius: 4, marginBottom: 10 }}>
          {status}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        {SCENARIOS.map((s) => (
          <button
            key={s.id}
            onClick={() => trigger(s.id)}
            disabled={loading}
            style={{
              background: active === s.id ? s.color + "22" : "#1e293b",
              border: `1px solid ${active === s.id ? s.color : "#334155"}`,
              borderRadius: 6,
              padding: "10px 12px",
              color: active === s.id ? s.color : "#cbd5e1",
              cursor: loading ? "wait" : "pointer",
              textAlign: "left",
              transition: "all 0.2s",
            }}
          >
            <div style={{ fontSize: 12, fontWeight: 600 }}>{s.label}</div>
            <div style={{ fontSize: 10, opacity: 0.7, marginTop: 2 }}>{s.description}</div>
          </button>
        ))}
      </div>
    </div>
  );
}
