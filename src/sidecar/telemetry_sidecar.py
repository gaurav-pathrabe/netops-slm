"""
telemetry_sidecar.py - Real-Time Telemetry Compression & Anomaly Sidecar
Inspired by NIKA architecture (2024). Filters high-volume switch/router logs,
extracts anomaly signatures, and compresses them into ~400-token prompt snapshots
for NetOps-SLM fine-tuning and inference.
"""

import os
import json
import logging
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

@dataclass
class TelemetrySnapshot:
    incident_id: str
    timestamp: str
    device: str
    severity: int
    severity_label: str
    category: str
    raw_signature: str
    anomaly_metrics: Dict[str, Any]
    prompt_context: str

class TelemetrySidecar:
    """
    Ingests raw syslog and telemetry metrics, isolates critical anomalies,
    and compresses context to under 400 tokens to preserve SLM context budget.
    """
    SEVERITY_MAP = {
        1: "EMERGENCY_ALERT",
        2: "CRITICAL",
        3: "ERROR",
        4: "WARNING",
        5: "NOTICE",
        6: "INFORMATIONAL"
    }

    def __init__(self, token_limit: int = 400):
        self.token_limit = token_limit

    def score_and_filter(self, log_entry: Dict[str, Any]) -> bool:
        """
        Filters out low-priority background noise (Severity 5+),
        retaining actionable operational incidents (Severity 1 to 4).
        """
        sev = log_entry.get("severity", 6)
        return sev <= 4

    def extract_anomaly_features(self, log_entry: Dict[str, Any]) -> Dict[str, Any]:
        """Extracts and normalizes abnormal telemetry metrics."""
        metrics = log_entry.get("telemetry_metric", {})
        anomalies = {}

        for k, v in metrics.items():
            # Flag metric thresholds
            if "drops" in k or "errors" in k or "crc" in k:
                if isinstance(v, (int, float)) and v > 0:
                    anomalies[k] = v
            elif "rx_power" in k:
                if isinstance(v, (int, float)) and v < -20.0:
                    anomalies[f"CRITICAL_{k}"] = f"{v} dBm (LOW)"
            elif "utilization" in k or "usage" in k:
                if isinstance(v, (int, float)) and v > 85.0:
                    anomalies[f"HIGH_{k}"] = f"{v}%"
            elif "state" in k:
                if str(v).upper() in ["IDLE", "DOWN", "EXSTART", "ROOT_INCONSISTENT"]:
                    anomalies[f"FAULT_{k}"] = v
            elif "offset" in k:
                if isinstance(v, (int, float)) and abs(v) > 500:
                    anomalies[f"DESYNC_{k}"] = f"{v} ms"
            else:
                anomalies[k] = v

        return anomalies

    def build_prompt_context(self, log_entry: Dict[str, Any], anomaly_features: Dict[str, Any], incident_idx: int) -> str:
        """
        Generates a concise 300 to 400 token prompt context representation.
        Designed specifically for Qwen2.5-Coder-1.5B prompt template.
        """
        device = log_entry.get("device", "unknown-device")
        source_ip = log_entry.get("source_ip", "0.0.0.0")
        facility = log_entry.get("facility", "SYS")
        mnemonic = log_entry.get("mnemonic", "ALERT")
        category = log_entry.get("category", "NETWORK_ANOMALY")
        raw_msg = log_entry.get("raw_message", "")
        description = log_entry.get("description", "")
        
        # Build clean YAML/JSON style telemetry block
        telemetry_lines = [f"  - {k}: {v}" for k, v in anomaly_features.items()]
        telemetry_block = "\n".join(telemetry_lines) if telemetry_lines else "  - None detected"

        prompt_context = (
            f"[INCIDENT TELEMETRY SNAPSHOT]\n"
            f"Device: {device} ({source_ip})\n"
            f"Fault Category: {category}\n"
            f"Syslog Trigger: %{facility}-{log_entry.get('severity')}-{mnemonic}\n"
            f"Message: {raw_msg}\n"
            f"Key Anomaly Metrics:\n{telemetry_block}\n"
            f"Incident Impact: {description}\n"
            f"[TASK: Diagnose root cause, predict secondary topology impact, and output verified rollback-safe CLI remediation.]"
        )
        return prompt_context

    def process_log_file(self, input_file: str, output_file: str) -> List[TelemetrySnapshot]:
        """Reads raw captured network logs and writes structured compressed snapshots."""
        if not os.path.exists(input_file):
            raise FileNotFoundError(f"Input log file not found: {input_file}")

        snapshots: List[TelemetrySnapshot] = []
        os.makedirs(os.path.dirname(output_file), exist_ok=True)

        with open(input_file, "r", encoding="utf-8") as fin:
            for idx, line in enumerate(fin, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if not self.score_and_filter(entry):
                    continue

                sev = entry.get("severity", 6)
                sev_label = self.SEVERITY_MAP.get(sev, "UNKNOWN")
                anomalies = self.extract_anomaly_features(entry)
                context_str = self.build_prompt_context(entry, anomalies, idx)

                snapshot = TelemetrySnapshot(
                    incident_id=f"INC-{idx:04d}",
                    timestamp=entry.get("ingest_timestamp", ""),
                    device=entry.get("device", "unknown"),
                    severity=sev,
                    severity_label=sev_label,
                    category=entry.get("category", "GENERAL"),
                    raw_signature=f"%{entry.get('facility')}-{sev}-{entry.get('mnemonic')}",
                    anomaly_metrics=anomalies,
                    prompt_context=context_str
                )
                snapshots.append(snapshot)

        with open(output_file, "w", encoding="utf-8") as fout:
            for snap in snapshots:
                fout.write(json.dumps(asdict(snap)) + "\n")

        logging.info(f"Sidecar processed {len(snapshots)} actionable incidents -> {output_file}")
        return snapshots


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    input_log_path = os.path.join(base_dir, "logs", "captured_network_logs.jsonl")
    output_snapshot_path = os.path.join(base_dir, "logs", "telemetry_snapshots.jsonl")

    sidecar = TelemetrySidecar(token_limit=400)
    print(f"[*] Running Telemetry Sidecar against: {input_log_path}")
    results = sidecar.process_log_file(input_log_path, output_snapshot_path)
    print(f"[+] Successfully generated {len(results)} compressed snapshots in {output_snapshot_path}\n")

    if results:
        print("[*] Sample Snapshot (Incident #1):")
        print("--------------------------------------------------")
        print(results[0].prompt_context)
        print("--------------------------------------------------")
