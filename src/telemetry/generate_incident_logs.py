"""
DEPRECATION NOTICE:
This synthetic incident generator is DEPRECATED per NetOps-SLM Master Plan Milestone 2.
Synthetic Cisco logs are NOT used for training or evaluation.
All authentic telemetry must be downloaded directly from the live FRR lab containers
using `lab/scripts/record_episode.py`.
"""

import socket
import time
import json
import random
import os

INCIDENT_SCENARIOS = [
    {
        "category": "BGP_SESSION_DOWN",
        "severity": 3,
        "facility": "BGP",
        "mnemonic": "ADJCHANGE",
        "device": "spine01-fra-dc",
        "device_ip": "10.250.0.1",
        "raw_syslog": "<187>241: *Sep 25 17:20:11.452: %BGP-3-NOTIFICATION: sent to neighbor 10.100.1.2 4/0 (hold time expired) 0 bytes",
        "telemetry_metric": {"bgp_peer": "10.100.1.2", "state": "IDLE", "prefixes_dropped": 45200, "flap_count": 5},
        "description": "BGP Hold Timer expired on spine-leaf interconnect, dropping 45,200 routes."
    },
    {
        "category": "ROCEV2_PFC_STORM",
        "severity": 2,
        "facility": "ETHPORT",
        "mnemonic": "IF_DOWN_PFC_WATCHDOG",
        "device": "leaf-ai-cluster04",
        "device_ip": "10.250.4.12",
        "raw_syslog": "<186>812: *Sep 25 17:21:05.109: %ETHPORT-2-IF_DOWN_PFC_WATCHDOG: Ethernet1/32 is down due to PFC Watchdog dead-lock mitigation",
        "telemetry_metric": {"interface": "Ethernet1/32", "pfc_rx_pause_frames": 4210980, "queue_depth_bytes": 16777216, "buffer_utilization_pct": 98.4},
        "description": "PFC Pause frame storm detected in GPU AI training fabric; Watchdog disabled interface to prevent fabric deadlock."
    },
    {
        "category": "OSPF_MTU_MISMATCH",
        "severity": 4,
        "facility": "OSPF",
        "mnemonic": "ADJCHANGE",
        "device": "wan-gw01-mumbai",
        "device_ip": "172.16.0.1",
        "raw_syslog": "<188>119: *Sep 25 17:22:33.201: %OSPF-4-ERRRCV: Received DBD packet with MTU 9000 from 172.16.1.2 on GigabitEthernet0/0/2 greater than MTU 1500",
        "telemetry_metric": {"interface": "GigabitEthernet0/0/2", "local_mtu": 1500, "remote_mtu": 9000, "ospf_state": "EXSTART"},
        "description": "OSPF neighbor stuck in EXSTART due to MTU mismatch on WAN link."
    },
    {
        "category": "OPTICAL_FIBER_DEGRADATION",
        "severity": 3,
        "facility": "TRANSCEIVER",
        "mnemonic": "OPTICAL_POWER_LOW",
        "device": "core01-subsea-oman",
        "device_ip": "10.200.0.5",
        "raw_syslog": "<187>552: *Sep 25 17:23:44.881: %TRANSCEIVER-3-OPTICAL_LOW: TenGigabitEthernet1/1/1 Rx power (-24.8 dBm) below warning threshold (-20.0 dBm)",
        "telemetry_metric": {"interface": "TenGigabitEthernet1/1/1", "rx_power_dbm": -24.8, "fec_uncorrectable_errors": 18450, "crc_drops": 4512},
        "description": "Subsea optical transponder Rx signal degrading rapidly, causing Forward Error Correction (FEC) bit failures."
    },
    {
        "category": "SPANNING_TREE_ROOT_INTRUSION",
        "severity": 2,
        "facility": "SPANTREE",
        "mnemonic": "ROOTGUARD_BLOCK",
        "device": "dist-sw02-bldg1",
        "device_ip": "10.50.2.2",
        "raw_syslog": "<186>993: *Sep 25 17:24:19.004: %SPANTREE-2-ROOTGUARD_BLOCK: Root guard blocking port GigabitEthernet0/24 on VLAN0010 due to received superior BPDU",
        "telemetry_metric": {"interface": "GigabitEthernet0/24", "vlan": 10, "spantree_state": "ROOT_INCONSISTENT", "blocked": True},
        "description": "Rogue switch advertised superior BPDU on access port; Spanning Tree Root Guard blocked the port to prevent topology hijack."
    },
    {
        "category": "BGP_ROUTE_LEAK",
        "severity": 1,
        "facility": "ROUTING",
        "mnemonic": "PREFIX_LIMIT_EXCEEDED",
        "device": "edge-border-router01",
        "device_ip": "198.51.100.1",
        "raw_syslog": "<185>402: *Sep 25 17:25:01.672: %ROUTING-1-BGP_PREFIX_LEAK: Peer 203.0.113.5 (AS64512) advertised 185,000 global prefixes exceeding limit of 500",
        "telemetry_metric": {"peer_as": 64512, "prefixes_received": 185000, "threshold_limit": 500, "action": "TEARDOWN"},
        "description": "BGP Route Leak detected from multihomed stub customer; maximum prefix shutdown executed."
    },
    {
        "category": "INTERFACE_CRC_BURST",
        "severity": 3,
        "facility": "LINEPROTO",
        "mnemonic": "UPDOWN",
        "device": "leaf-rack12",
        "device_ip": "10.10.12.1",
        "raw_syslog": "<187>301: *Sep 25 17:25:40.118: %LINEPROTO-3-UPDOWN: Line protocol on Interface HundredGigE0/0/0/1, changed state to down (CRC error rate exceeded)",
        "telemetry_metric": {"interface": "HundredGigE0/0/0/1", "crc_errors_per_sec": 8420, "input_errors": 492100, "link_flaps_last_10m": 8},
        "description": "DAC cable fault on 100G uplink switch port causing continuous CRC error bursts."
    },
    {
        "category": "HSRP_SPLIT_BRAIN",
        "severity": 2,
        "facility": "HSRP",
        "mnemonic": "STATECHANGE",
        "device": "aggr-sw01",
        "device_ip": "10.20.1.1",
        "raw_syslog": "<186>771: *Sep 25 17:26:12.511: %HSRP-2-ACTIVE_CONFLICT: Vlan20 Grp 20 duplicate active router 10.20.20.2 detected with higher priority",
        "telemetry_metric": {"vlan": 20, "hsrp_group": 20, "local_state": "ACTIVE", "remote_ip": "10.20.20.2", "heartbeat_lost": True},
        "description": "HSRP heartbeat lost across inter-switch link; dual active routers causing IP gateway IP conflict."
    },
    {
        "category": "MEMORY_EXHAUSTION_TCAM",
        "severity": 2,
        "facility": "PLATFORM",
        "mnemonic": "TCAM_FULL",
        "device": "core-nexus-9k",
        "device_ip": "10.0.0.1",
        "raw_syslog": "<186>918: *Sep 25 17:27:01.319: %PLATFORM-2-TCAM_FULL: Hardware TCAM table exhausted for IPv4 unicast routing. 12,410 routes running in software slow-path",
        "telemetry_metric": {"tcam_usage_pct": 100.0, "software_forwarded_pps": 850000, "cpu_utilization_pct": 94.2},
        "description": "Hardware TCAM full due to unaggregated routing table; packets punted to supervisor CPU causing latency spike."
    },
    {
        "category": "NTP_CLOCK_DESYNC",
        "severity": 4,
        "facility": "NTP",
        "mnemonic": "UNSYNC",
        "device": "ptp-grandmaster-edge",
        "device_ip": "10.30.0.10",
        "raw_syslog": "<188>114: *Sep 25 17:28:15.908: %NTP-4-UNSYNC: System clock offset (1450.2 ms) exceeds stratum threshold; PTP synchronization lost",
        "telemetry_metric": {"ntp_offset_ms": 1450.2, "ptp_lock": False, "stratum": 16},
        "description": "Grandmaster clock reference lost; high-frequency financial telemetry timestamps out of compliance."
    }
]

def stream_logs_udp(host="127.0.0.1", port=5514, delay=0.5):
    """Streams simulated enterprise network incident logs over UDP to syslog_collector."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"[+] Starting live incident log streaming to UDP {host}:{port}")
    
    for i, incident in enumerate(INCIDENT_SCENARIOS, 1):
        payload = incident["raw_syslog"].encode("utf-8")
        sock.sendto(payload, (host, port))
        print(f"[{i}/{len(INCIDENT_SCENARIOS)}] Sent: {incident['category']} from {incident['device']}")
        time.sleep(delay)
        
    sock.close()
    print("[✓] Incident streaming complete.")

def save_raw_dataset(output_path="logs/captured_network_logs.jsonl"):
    """Writes the structured incident logs directly to JSONL file for sidecar processing."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for incident in INCIDENT_SCENARIOS:
            record = {
                "ingest_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "source_ip": incident["device_ip"],
                "facility": incident["facility"],
                "severity": incident["severity"],
                "mnemonic": incident["mnemonic"],
                "device": incident["device"],
                "category": incident["category"],
                "raw_message": incident["raw_syslog"],
                "telemetry_metric": incident["telemetry_metric"],
                "description": incident["description"]
            }
            f.write(json.dumps(record) + "\n")
    print(f"[✓] Saved {len(INCIDENT_SCENARIOS)} rich enterprise network incidents to: {output_path}")

if __name__ == "__main__":
    save_raw_dataset()
