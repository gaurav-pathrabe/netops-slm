"""
syslog_collector.py - Real-Time Syslog & Telemetry Receiver for NetOps-SLM
Captures Cisco IOS-XE, NX-OS, Arista EOS, and Linux syslog streams over UDP,
parses them into structured JSON events, and stores them for LLM ingestion.
"""

import socket
import json
import re
import datetime
import os
from typing import Dict, Any, Optional

# Standard Cisco/RFC3164 Syslog Regex
# Example: <189>124: *Sep 25 17:15:00.123: %LINEPROTO-5-UPDOWN: Line protocol on Interface Gi0/1, changed state to down
CISCO_SYSLOG_PATTERN = re.compile(
    r'^(?:<(?P<pri>\d+)>)?(?:(?P<seq>\d+):)?\s*'
    r'(?:\*(?P<timestamp>[A-Za-z0-9\s:\.]+):)?\s*'
    r'(?:%(?P<facility>[A-Z0-9_]+)-(?P<severity>\d)-(?P<mnemonic>[A-Z0-9_]+):\s*)?'
    r'(?P<message>.*)$'
)

class SyslogCollector:
    def __init__(self, host: str = "0.0.0.0", port: int = 5514, log_dir: str = "logs"):
        self.host = host
        self.port = port
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)
        self.output_file = os.path.join(self.log_dir, "captured_network_logs.jsonl")

    def parse_syslog(self, raw_data: str, source_ip: str) -> Dict[str, Any]:
        """Parses raw syslog string into a structured dictionary."""
        match = CISCO_SYSLOG_PATTERN.match(raw_data.strip())
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        if match:
            parsed = match.groupdict()
            return {
                "ingest_timestamp": now,
                "source_ip": source_ip,
                "facility": parsed.get("facility") or "SYSTEM",
                "severity": int(parsed.get("severity") or 6),
                "mnemonic": parsed.get("mnemonic") or "UNKNOWN",
                "device_timestamp": parsed.get("timestamp") or now,
                "raw_message": parsed.get("message") or raw_data.strip(),
                "full_raw": raw_data.strip()
            }
        
        return {
            "ingest_timestamp": now,
            "source_ip": source_ip,
            "facility": "UNKNOWN",
            "severity": 6,
            "mnemonic": "UNKNOWN",
            "device_timestamp": now,
            "raw_message": raw_data.strip(),
            "full_raw": raw_data.strip()
        }

    def start(self, max_packets: Optional[int] = None):
        """Starts listening for incoming UDP syslog packets."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind((self.host, self.port))
            print(f"[+] Syslog Collector active and listening on UDP {self.host}:{self.port}")
            print(f"[+] Storing parsed logs to: {self.output_file}")
            print("[*] Press Ctrl+C to stop listening...\n")
            
            packet_count = 0
            with open(self.output_file, "a", encoding="utf-8") as f:
                while True:
                    data, addr = sock.recvfrom(4096)
                    raw_str = data.decode("utf-8", errors="replace")
                    event = self.parse_syslog(raw_str, addr[0])
                    
                    # Print formatted event to console
                    sev_symbol = "🚨" if event["severity"] <= 3 else "⚠️" if event["severity"] <= 5 else "ℹ️"
                    print(f"{sev_symbol} [{event['facility']}-{event['severity']}-{event['mnemonic']}] ({addr[0]}): {event['raw_message']}")
                    
                    # Append JSONL record
                    f.write(json.dumps(event) + "\n")
                    f.flush()
                    
                    packet_count += 1
                    if max_packets and packet_count >= max_packets:
                        print(f"\n[✓] Collected requested limit of {max_packets} packets.")
                        break

        except KeyboardInterrupt:
            print("\n[-] Stopping Syslog Collector. Safe shutdown complete.")
        finally:
            sock.close()

if __name__ == "__main__":
    collector = SyslogCollector(port=5514)
    collector.start()
