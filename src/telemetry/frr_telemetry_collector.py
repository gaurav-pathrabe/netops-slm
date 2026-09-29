"""
frr_telemetry_collector.py - Authentic FRR Log Collector & Telemetry Ingestion
Parses real FRR daemon outputs, preserving original messages, origin timestamps,
daemon names, severities, and error codes.
Adheres to NetOps-SLM Milestone 2 requirements.
"""

import re
import json
import os
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

# FRR Log Format:
# Example: 2026/09/29 18:25:00 BGP: %ADJCHANGE: neighbor 10.77.0.2(PEER_ROUTER_B) in vrf default Down Admin. shutdown
# Example: 2026/09/29 18:25:05 BGP: [EC 33554452] %NOTIFICATION: sent to neighbor 10.77.0.2 6/2 (Cease/Administrative Shutdown) 0 bytes
FRR_LOG_PATTERN = re.compile(
    r'^(?P<timestamp>\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+'
    r'(?P<daemon>[A-Z0-9_]+):\s+'
    r'(?:\[(?:EC\s+)?(?P<ec>\d+)\]\s+)?'
    r'(?:%(?P<mnemonic>[A-Z0-9_]+):\s+)?'
    r'(?P<message>.*)$'
)

class FRRTelemetryCollector:
    def __init__(self, raw_log_file: Optional[str] = None):
        self.raw_log_file = raw_log_file

    def parse_line(self, line: str, device: str = "router-a") -> Dict[str, Any]:
        """Parses a single FRR log line, preserving full raw content and error codes."""
        now = datetime.now(timezone.utc).isoformat()
        match = FRR_LOG_PATTERN.match(line.strip())

        if match:
            d = match.groupdict()
            return {
                "ingest_timestamp": now,
                "origin_timestamp": d["timestamp"],
                "device": device,
                "daemon": d["daemon"],
                "error_code": d.get("ec"),
                "mnemonic": d.get("mnemonic") or "LOG",
                "raw_message": d["message"].strip(),
                "full_raw": line.strip(),
                "parsed": True
            }

        return {
            "ingest_timestamp": now,
            "origin_timestamp": None,
            "device": device,
            "daemon": "UNKNOWN",
            "error_code": None,
            "mnemonic": "UNKNOWN",
            "raw_message": line.strip(),
            "full_raw": line.strip(),
            "parsed": False
        }

    def group_events_into_snapshot(
        self,
        events: List[Dict[str, Any]],
        bgp_state: Optional[Dict[str, Any]] = None,
        route_state: Optional[List[str]] = None,
        device: str = "router-a"
    ) -> Dict[str, Any]:
        """
        Groups authentic events and current read-only network state into a
        compact ~400 token evidence snapshot for base-model / runbook reasoning.
        """
        evidence_items = []
        for idx, ev in enumerate(events, 1):
            evidence_items.append({
                "id": f"event_{idx}",
                "daemon": ev.get("daemon"),
                "mnemonic": ev.get("mnemonic"),
                "message": ev.get("raw_message"),
                "origin_timestamp": ev.get("origin_timestamp")
            })

        return {
            "snapshot_id": f"snap_{int(datetime.now(timezone.utc).timestamp())}",
            "device": device,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "telemetry_evidence": evidence_items,
            "state_snapshot": {
                "bgp_neighbor_summary": bgp_state or {},
                "active_routes": route_state or []
            },
            "task": "Produce a typed action JSON adhering to NetOps-SLM schema or abstain if uncertain."
        }


if __name__ == "__main__":
    sample_frr_logs = [
        "2026/09/29 18:25:00 BGP: %ADJCHANGE: neighbor 10.77.0.2(PEER_ROUTER_B) in vrf default Down Admin. shutdown",
        "2026/09/29 18:25:00 BGP: [EC 33554452] %NOTIFICATION: sent to neighbor 10.77.0.2 6/2 (Cease/Administrative Shutdown) 0 bytes"
    ]

    collector = FRRTelemetryCollector()
    parsed_events = [collector.parse_line(log, device="router-a") for log in sample_frr_logs]
    
    bgp_state = {
        "peer": "10.77.0.2",
        "remote_as": 65002,
        "state": "Idle (Admin)"
    }
    
    snapshot = collector.group_events_into_snapshot(parsed_events, bgp_state=bgp_state, device="router-a")
    print(json.dumps(snapshot, indent=2))
