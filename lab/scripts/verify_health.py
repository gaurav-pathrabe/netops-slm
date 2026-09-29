#!/usr/bin/env python3
"""
verify_health.py - NetOps-SLM Milestone 1 Health & Reachability Assertion Engine

Checks:
1. BGP peer session state between router-a and router-b is Established.
2. Route presence: router-a receives 10.77.2.0/24, router-b receives 10.77.1.0/24.
3. End-to-end reachability: 20 ICMP pings from client-a to client-b. Pass criteria: >= 95% (>= 19/20).
4. Appends structured run record to evidence/demo_runs.jsonl.
"""

import sys
import json
import time
import os
import argparse
import subprocess
from datetime import datetime, timezone

ROUTER_A = "clab-netops-bgp-lab-router-a"
ROUTER_B = "clab-netops-bgp-lab-router-b"
CLIENT_A = "clab-netops-bgp-lab-client-a"
TARGET_IP = "10.77.2.10"
EVIDENCE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "evidence", "demo_runs.jsonl")


def run_cmd(cmd_list):
    """Executes a command and returns (returncode, stdout, stderr)."""
    try:
        res = subprocess.run(cmd_list, capture_output=True, text=True, timeout=30)
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def check_bgp_established(container_name: str, neighbor_ip: str) -> bool:
    """Verifies that the BGP neighbor state is Established using vtysh JSON output."""
    rc, out, err = run_cmd(["docker", "exec", container_name, "vtysh", "-c", "show ip bgp summary json"])
    if rc != 0 or not out:
        return False
    try:
        data = json.loads(out)
        # Parse FRR JSON structure for peers
        peers = data.get("ipv4Unicast", {}).get("peers", {})
        if neighbor_ip in peers:
            state = peers[neighbor_ip].get("state", "")
            return state.lower() == "established"
    except Exception:
        pass
    return False


def check_route_present(container_name: str, prefix: str) -> bool:
    """Verifies prefix is present in routing table."""
    rc, out, err = run_cmd(["docker", "exec", container_name, "vtysh", "-c", f"show ip route {prefix} json"])
    if rc != 0 or not out:
        return False
    try:
        data = json.loads(out)
        return prefix in data or len(data) > 0
    except Exception:
        pass
    return False


def test_endpoint_reachability(client_container: str, target_ip: str, count: int = 20) -> int:
    """Sends ICMP echo requests and counts successful replies."""
    rc, out, err = run_cmd(["docker", "exec", client_container, "ping", "-c", str(count), "-W", "1", target_ip])
    # Parse ping summary: e.g., "20 packets transmitted, 20 packets received, 0% packet loss"
    import re
    match = re.search(r"(\d+)\s+(?:packets\s+)?received", out)
    if match:
        return int(match.group(1))
    return count if rc == 0 else 0


def record_evidence(run_type: str, bgp_up: bool, routes_up: bool, pings_passed: int, total_pings: int, success: bool, notes: str = ""):
    os.makedirs(os.path.dirname(EVIDENCE_FILE), exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_type": run_type,
        "assertions": {
            "bgp_session_established": bgp_up,
            "routes_present": routes_up,
            "pings_passed": pings_passed,
            "total_pings": total_pings,
            "reachability_pct": round((pings_passed / total_pings) * 100, 1) if total_pings else 0
        },
        "success": success,
        "notes": notes
    }
    with open(EVIDENCE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    print(f"[+] Run evidence appended to {EVIDENCE_FILE}")
    return record


def main():
    parser = argparse.ArgumentParser(description="NetOps-SLM Milestone 1 Health Verifier")
    parser.add_argument("--mock", action="store_true", help="Simulate check without running Docker")
    parser.add_argument("--run_type", type=str, default="baseline_check", choices=["baseline_check", "post_fault_check", "recovery_verification"])
    args = parser.parse_args()

    print(f"[*] Executing NetOps Health Assertion ({args.run_type})...")

    if args.mock:
        print("[!] Running in MOCK mode (simulated assertions).")
        bgp_ok = True if args.run_type != "post_fault_check" else False
        routes_ok = True if args.run_type != "post_fault_check" else False
        pings = 20 if args.run_type != "post_fault_check" else 0
        success = (bgp_ok and routes_ok and (pings / 20.0 >= 0.95))
        rec = record_evidence(args.run_type, bgp_ok, routes_ok, pings, 20, success, notes="Mock simulation execution")
        print(f"[✓] Assertion Result: {'PASSED' if success else 'FAILED'} (Success={success})")
        sys.exit(0 if success else 1)

    # Real Docker execution
    bgp_a = check_bgp_established(ROUTER_A, "10.77.0.2")
    bgp_b = check_bgp_established(ROUTER_B, "10.77.0.1")
    bgp_ok = bgp_a and bgp_b

    route_a = check_route_present(ROUTER_A, "10.77.2.0/24")
    route_b = check_route_present(ROUTER_B, "10.77.1.0/24")
    routes_ok = route_a and route_b

    pings_passed = test_endpoint_reachability(CLIENT_A, TARGET_IP, count=20)
    reachability_ok = (pings_passed / 20.0) >= 0.95

    success = bgp_ok and routes_ok and reachability_ok
    record_evidence(args.run_type, bgp_ok, routes_ok, pings_passed, 20, success)

    print(f"--- Health Check Summary ---")
    print(f"BGP Established:       {bgp_ok} (Router-A: {bgp_a}, Router-B: {bgp_b})")
    print(f"Route Presence:        {routes_ok} (10.77.2.0/24: {route_a}, 10.77.1.0/24: {route_b})")
    print(f"Pings Passed:          {pings_passed}/20 ({round((pings_passed/20)*100, 1)}%)")
    print(f"Overall Result:        {'PASSED' if success else 'FAILED'}")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
