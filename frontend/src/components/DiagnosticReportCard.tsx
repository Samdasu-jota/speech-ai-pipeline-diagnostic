/**
 * DiagnosticReportCard — renders a single DiagnosticReport.
 *
 * Displays the report ID, timestamp, pipeline status, RCA section
 * (probable cause + evidence + fix), and key metrics snapshot.
 */

import React, { useState } from "react";
import type { DiagnosticReport } from "../hooks/usePipelineAlerts";

interface Props {
  report: DiagnosticReport;
}

const STATUS_COLOR: Record<string, string> = {
  HEALTHY: "#22c55e",
  DEGRADED: "#f59e0b",
  CRITICAL: "#ef4444",
};

export function DiagnosticReportCard({ report }: Props) {
  const [expanded, setExpanded] = useState(false);
  const rca = report.root_cause_analysis;
  const color = STATUS_COLOR[report.pipeline_status] || "#94a3b8";

  return (
    <div
      style={{
        border: `1px solid ${color}44`,
        borderLeft: `4px solid ${color}`,
        borderRadius: 8,
        padding: "14px 16px",
        marginBottom: 12,
        background: "#0f172a",
        cursor: "pointer",
      }}
      onClick={() => setExpanded((e) => !e)}
    >
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <span style={{ fontSize: 10, color: "#64748b", fontFamily: "monospace" }}>
            {report.report_id}
          </span>
          <div style={{ fontSize: 13, fontWeight: 700, color, marginTop: 2 }}>
            {report.pipeline_status} — {rca.probable_cause}
          </div>
        </div>
        <div style={{ fontSize: 11, color: "#475569", textAlign: "right" }}>
          <div>{new Date(report.timestamp).toLocaleTimeString()}</div>
          <div style={{ marginTop: 2 }}>
            Confidence: <strong style={{ color }}>{(rca.confidence * 100).toFixed(0)}%</strong>
          </div>
        </div>
      </div>

      {expanded && (
        <div style={{ marginTop: 14 }}>
          {/* Evidence */}
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#94a3b8", marginBottom: 6, textTransform: "uppercase" }}>
              Evidence
            </div>
            {rca.evidence.map((e, i) => (
              <div key={i} style={{ fontSize: 11, color: "#cbd5e1", marginBottom: 3, paddingLeft: 10, borderLeft: "2px solid #334155" }}>
                {e}
              </div>
            ))}
          </div>

          {/* Suggested fix */}
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#94a3b8", marginBottom: 4, textTransform: "uppercase" }}>
              Suggested Fix
            </div>
            <div style={{ fontSize: 11, color: "#86efac", background: "#14532d22", borderRadius: 4, padding: "6px 10px" }}>
              {rca.suggested_fix}
            </div>
          </div>

          {/* Metrics snapshot */}
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#94a3b8", marginBottom: 6, textTransform: "uppercase" }}>
              Metrics at Detection
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 16px" }}>
              {Object.entries(report.metrics_snapshot).map(([key, val]) => (
                <div key={key} style={{ fontSize: 10, color: "#64748b" }}>
                  <span style={{ color: "#94a3b8" }}>{key.replace(/_/g, " ")}</span>: {val}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
