/**
 * PipelineHealthGrid — shows per-stage health status as a colour-coded grid.
 *
 * Each stage card displays its DTC-style status code and health colour,
 * analogous to the component health grid in Tesla's service mode interface.
 */

import React from "react";

interface Props {
  stageHealth: Record<string, string>;
  stageLatencies?: Record<string, number>;
}

const STAGE_ORDER = [
  { key: "audio_capture", label: "Audio Capture", icon: "🎙" },
  { key: "speech_to_text", label: "Speech-to-Text", icon: "📝" },
  { key: "language_processing", label: "Language Proc.", icon: "🔤" },
  { key: "llm", label: "LLM Correction", icon: "🤖" },
  { key: "output", label: "Output", icon: "📤" },
  { key: "system", label: "System", icon: "🖥" },
];

const STATUS_STYLES: Record<string, React.CSSProperties> = {
  HEALTHY: { background: "#14532d", borderColor: "#22c55e", color: "#86efac" },
  DEGRADED: { background: "#713f12", borderColor: "#f59e0b", color: "#fde68a" },
  CRITICAL: { background: "#7f1d1d", borderColor: "#ef4444", color: "#fca5a5" },
};

export function PipelineHealthGrid({ stageHealth, stageLatencies }: Props) {
  return (
    <div style={{ marginBottom: 24 }}>
      <h2 style={{ fontSize: 14, fontWeight: 600, color: "#94a3b8", marginBottom: 12, letterSpacing: 1, textTransform: "uppercase" }}>
        Pipeline Stage Health
      </h2>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
        {STAGE_ORDER.map(({ key, label, icon }) => {
          const status = stageHealth[key] || "HEALTHY";
          const style = STATUS_STYLES[status] || STATUS_STYLES.HEALTHY;
          const latency = stageLatencies?.[key];
          return (
            <div
              key={key}
              style={{
                ...style,
                border: `2px solid`,
                borderRadius: 8,
                padding: "12px 14px",
              }}
            >
              <div style={{ fontSize: 20, marginBottom: 4 }}>{icon}</div>
              <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 2 }}>{label}</div>
              <div style={{ fontSize: 11, opacity: 0.8 }}>{status}</div>
              {latency !== undefined && (
                <div style={{ fontSize: 10, opacity: 0.6, marginTop: 2 }}>
                  {latency.toFixed(0)} ms
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
