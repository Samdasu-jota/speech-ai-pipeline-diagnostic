"""
SystemMonitor — background thread that polls CPU and memory utilisation
and pushes values into the MetricsRegistry every `interval` seconds.
"""

from __future__ import annotations

import logging
import threading
import time

import psutil

from .metrics_registry import MetricsRegistry

logger = logging.getLogger(__name__)


class SystemMonitor(threading.Thread):
    """
    Daemon thread that continuously samples system resource metrics.

    Usage:
        monitor = SystemMonitor(interval=5)
        monitor.start()          # call once at app startup
        ...
        monitor.stop()
    """

    def __init__(self, interval: float = 5.0) -> None:
        super().__init__(daemon=True, name="SystemMonitor")
        self.interval = interval
        self._stop_event = threading.Event()
        self.registry = MetricsRegistry.instance()

    def run(self) -> None:
        logger.info("SystemMonitor started", extra={"interval_s": self.interval})
        while not self._stop_event.wait(timeout=self.interval):
            try:
                cpu = psutil.cpu_percent(interval=None)
                mem = psutil.virtual_memory().percent
                self.registry.set_metric("system_cpu_percent", cpu)
                self.registry.set_metric("system_memory_percent", mem)
                logger.debug(
                    "system_metrics_sampled",
                    extra={"cpu_percent": cpu, "memory_percent": mem},
                )
            except Exception:
                logger.exception("SystemMonitor sampling error")

    def stop(self) -> None:
        self._stop_event.set()
        logger.info("SystemMonitor stopped")
