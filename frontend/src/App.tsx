/**
 * App — main dashboard layout for the Speech AI Diagnostic System.
 *
 * Layout:
 *   Header (system status, WS connection indicator)
 *   ├── Left column:  PipelineHealthGrid, MetricsPanel
 *   └── Right column: AlertFeed, DiagnosticReportCard list
 *   Bottom: SimulationControls
 */

import React, { useEffect, useState } from "react";
import { usePipelineAlerts } from "./hooks/usePipelineAlerts";
import { PipelineHealthGrid } from "./components/PipelineHealthGrid";
import { AlertFeed } from "./components/AlertFeed";
import { DiagnosticReportCard } from "./components/DiagnosticReportCard";
import { SimulationControls } from "./components/SimulationControls";

const METRIC_LABELS: Record<string, string> = {
  stt_word_error_rate: "WER",
  audio_snr_db: "Audio SNR (dB)",
  llm_api_latency_p99_ms: "LLM P99 (ms)",
  system_cpu_percent: "CPU %",
  system_memory_percent: "Memory %",
  pipeline_e2e_latency_p99_ms: "E2E P99 (ms)",
  llm_error_rate_429: "LLM 429 Rate",
};

export default function App() {
  const { reports, latestReport, connected } = usePipelineAlerts();
  const [polledMetrics, setPolledMetrics] = useState<Record<string, number>>({});

  // Poll /api/pipeline/status every 5s as fallback when no WS report
  useEffect(() => {
    const poll = async () => {
      try {
        const res = await fetch("/api/pipeline/status");
        const data = await res.json();
        setPolledMetrics(data.metrics || {});
      } catch {
        // backend not yet ready
      }
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => clearInterval(id);
  }, []);

  const metrics = latestReport?.metrics_snapshot || polledMetrics;
  const stageHealth = latestReport?.stage_health || {};
  const activeAlerts = latestReport?.active_alerts || [];

  const systemStatus = latestReport?.pipeline_status || "HEALTHY";
  const statusColor =
    systemStatus === "CRITICAL" ? "#ef4444" :
    systemStatus === "DEGRADED" ? "#f59e0b" : "#22c55e";

  return (
    <div style={{ minHeight: "100vh", background: "#0a0e1a", color: "#e2e8f0", fontFamily: "monospace" }}>
      {/* ── Header ────────────────────────────────────────────────── */}
      <header
        style={{
          background: "#0f172a",
          borderBottom: "1px solid #1e293b",
          padding: "12px 24px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: "#f1f5f9" }}>
            Speech AI Diagnostic System
          </div>
          <div style={{ fontSize: 10, color: "#475569", marginTop: 2 }}>
            Automated Pipeline Fault Detection &amp; Root Cause Analysis
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: statusColor }}>
            ● {systemStatus}
          </div>
          <div
            style={{
              fontSize: 10,
              color: connected ? "#22c55e" : "#ef4444",
              background: connected ? "#14532d22" : "#7f1d1d22",
              border: `1px solid ${connected ? "#22c55e" : "#ef4444"}`,
              borderRadius: 4,
              padding: "2px 8px",
            }}
          >
            {connected ? "WS LIVE" : "WS OFFLINE"}
          </div>
        </div>
      </header>

      {/* ── Main layout ───────────────────────────────────────────── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 16,
          padding: 24,
          maxWidth: 1400,
          margin: "0 auto",
        }}
      >
        {/* ── Left: health grid + metrics ───────────── */}
        <div>
          <PipelineHealthGrid stageHealth={stageHealth} />

          {/* Metrics panel */}
          <div
            style={{
              background: "#0f172a",
              border: "1px solid #1e293b",
              borderRadius: 8,
              padding: 16,
              marginBottom: 16,
            }}
          >
            <h2 style={{ fontSize: 14, fontWeight: 600, color: "#94a3b8", marginBottom: 12, letterSpacing: 1, textTransform: "uppercase" }}>
              Live Metrics
            </h2>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px 16px" }}>
              {Object.entries(METRIC_LABELS).map(([key, label]) => {
                const val = metrics[key];
                return (
                  <div key={key} style={{ fontSize: 12 }}>
                    <div style={{ color: "#64748b", fontSize: 10 }}>{label}</div>
                    <div style={{ color: "#f1f5f9", fontWeight: 600, fontSize: 14 }}>
                      {val !== undefined ? val.toFixed(3) : "—"}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Simulation controls */}
          <div
            style={{
              background: "#0f172a",
              border: "1px solid #1e293b",
              borderRadius: 8,
              padding: 16,
            }}
          >
            <SimulationControls />
          </div>
        </div>

        {/* ── Right: alerts + reports ────────────────── */}
        <div>
          <div
            style={{
              background: "#0f172a",
              border: "1px solid #1e293b",
              borderRadius: 8,
              padding: 16,
              marginBottom: 16,
            }}
          >
            <h2 style={{ fontSize: 14, fontWeight: 600, color: "#94a3b8", marginBottom: 8, letterSpacing: 1, textTransform: "uppercase" }}>
              Active Alerts ({activeAlerts.length})
            </h2>
            <AlertFeed alerts={activeAlerts} />
          </div>

          <div
            style={{
              background: "#0f172a",
              border: "1px solid #1e293b",
              borderRadius: 8,
              padding: 16,
              maxHeight: 520,
              overflowY: "auto",
            }}
          >
            <h2 style={{ fontSize: 14, fontWeight: 600, color: "#94a3b8", marginBottom: 12, letterSpacing: 1, textTransform: "uppercase" }}>
              Diagnostic Reports ({reports.length})
            </h2>
            {reports.length === 0 ? (
              <div style={{ fontSize: 13, color: "#475569" }}>
                No reports yet — inject a fault or wait for pipeline telemetry to accumulate.
              </div>
            ) : (
              reports.map((r) => <DiagnosticReportCard key={r.report_id} report={r} />)
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
