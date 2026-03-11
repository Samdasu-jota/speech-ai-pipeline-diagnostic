/**
 * usePipelineAlerts — WebSocket hook for live diagnostic report streaming.
 *
 * Connects to /ws/diagnostics and pushes incoming reports and alerts
 * into component state. Reconnects automatically on disconnect.
 */

import { useState, useEffect, useCallback, useRef } from "react";

export interface AlertItem {
  rule_id: string;
  dtc_code: string;
  severity: "INFO" | "WARN" | "CRITICAL";
  message: string;
  current_value: number;
  baseline_value: number | null;
  stage: string;
}

export interface RCAResult {
  probable_cause: string;
  confidence: number;
  evidence: string[];
  suggested_fix: string;
  matched_rule_id: string;
  affected_stages: string[];
}

export interface DiagnosticReport {
  report_id: string;
  timestamp: string;
  pipeline_status: "HEALTHY" | "DEGRADED" | "CRITICAL";
  active_alerts: AlertItem[];
  root_cause_analysis: RCAResult;
  stage_health: Record<string, string>;
  metrics_snapshot: Record<string, number>;
}

const WS_URL = `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws/diagnostics`;
const RECONNECT_DELAY_MS = 3000;

export function usePipelineAlerts() {
  const [reports, setReports] = useState<DiagnosticReport[]>([]);
  const [latestReport, setLatestReport] = useState<DiagnosticReport | null>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "diagnostic_report") {
          const report: DiagnosticReport = msg.data;
          setLatestReport(report);
          setReports((prev) => [report, ...prev].slice(0, 50)); // keep last 50
        }
      } catch {
        // ignore malformed messages
      }
    };

    ws.onclose = () => {
      setConnected(false);
      reconnectRef.current = setTimeout(connect, RECONNECT_DELAY_MS);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { reports, latestReport, connected };
}
