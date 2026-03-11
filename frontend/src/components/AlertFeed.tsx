/**
 * AlertFeed — live stream of fired diagnostic alerts.
 *
 * Each entry shows the DTC code, severity badge, and alert message.
 * New alerts appear at the top with a brief highlight animation.
 */

import React from "react";
import type { AlertItem } from "../hooks/usePipelineAlerts";

interface Props {
  alerts: AlertItem[];
}

const SEVERITY_COLOR: Record<string, string> = {
  CRITICAL: "#ef4444",
  WARN: "#f59e0b",
  INFO: "#3b82f6",
};

export function AlertFeed({ alerts }: Props) {
  if (alerts.length === 0) {
    return (
      <div style={{ padding: "16px 0", color: "#64748b", fontSize: 13 }}>
        No active alerts — pipeline operating normally.
      </div>
    );
  }

  return (
    <div>
      {alerts.map((alert, i) => (
        <div
          key={`${alert.rule_id}-${i}`}
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 12,
            padding: "10px 0",
            borderBottom: "1px solid #1e293b",
          }}
        >
          <span
            style={{
              background: SEVERITY_COLOR[alert.severity] + "22",
              color: SEVERITY_COLOR[alert.severity],
              border: `1px solid ${SEVERITY_COLOR[alert.severity]}`,
              borderRadius: 4,
              padding: "2px 6px",
              fontSize: 10,
              fontWeight: 700,
              whiteSpace: "nowrap",
              minWidth: 64,
              textAlign: "center",
            }}
          >
            {alert.dtc_code}
          </span>
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: SEVERITY_COLOR[alert.severity] }}>
              [{alert.severity}]
            </div>
            <div style={{ fontSize: 12, color: "#cbd5e1", marginTop: 2 }}>{alert.message}</div>
            <div style={{ fontSize: 10, color: "#64748b", marginTop: 2 }}>
              current: {alert.current_value.toFixed(3)}
              {alert.baseline_value !== null && ` / baseline: ${alert.baseline_value.toFixed(3)}`}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
