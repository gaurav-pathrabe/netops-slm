#!/usr/bin/env python3
"""
verify_spine_leaf.py - NetOps-SLM Phase 2 CLOS Spine-Leaf Fabric Assertion Engine

Verifies:
1. All 4 BGP switches (spine-1, spine-2, leaf-1, leaf-2) have Established eBGP sessions.
2. Equal-Cost Multi-Path (ECMP) route installation:
   - leaf-1 has 2 nexthops for 10.77.2.0/24 (multipath via spine-1 and spine-2).
   - leaf-2 has 2 nexthops for 10.77.1.0/24 (multipath via spine-1 and spine-2).
3. End-to-end bidirectional ICMP ping reachability between client-1 and client-2.
4. Appends structured run evidence to evidence/spine_leaf_runs.jsonl.
"""

import sys
import json
import time
import os
import argparse
import subprocess
import re
from datetime import datetime, timezone

PREFIX = "clab-netops-spine-leaf-lab-"
SPINE_1 = f"{PREFIX}spine-1"
SPINE_2 = f"{PREFIX}spine-2"
LEAF_1 = f"{PREFIX}leaf-1"
LEAF_2 = f"{PREFIX}leaf-2"
CLIENT_1 = f"{PREFIX}client-1"
CLIENT_2 = f"{PREFIX}client-2"

EVIDENCE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "evidence",
    "spine_leaf_runs.jsonl"
)


def run_cmd(cmd_list):
    """Executes a command and returns (returncode, stdout, stderr)."""
    try:
        res = subprocess.run(cmd_list, capture_output=True, text=True, timeout=30)
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def check_bgp_peer(container_name: str, neighbor_ip: str) -> bool:
    """Verifies that BGP neighbor state is Established using vtysh JSON."""
    rc, out, _ = run_cmd(["docker", "exec", container_name, "vtysh", "-c", "show ip bgp summary json"])
    if rc != 0 or not out:
        return False
    try:
        data = json.loads(out)
        peers = data.get("ipv4Unicast", {}).get("peers", {})
        if neighbor_ip in peers:
            state = peers[neighbor_ip].get("state", "")
            return state.lower() == "established"
    except Exception:
        pass
    return False


def check_ecmp_route(leaf_container: str, destination_prefix: str) -> dict:
    """Checks if the destination prefix has multipath (>= 2 nexthops) installed."""
    rc, out, _ = run_cmd(["docker", "exec", leaf_container, "vtysh", "-c", f"show ip route {destination_prefix} json"])
    result = {"present": False, "multipath": False, "nexthops": []}
    if rc != 0 or not out:
        return result
    try:
        data = json.loads(out)
        if destination_prefix in data:
            entry = data[destination_prefix]
            routes = entry if isinstance(entry, list) else [entry]
            for r in routes:
                nexthops = r.get("nexthops", [])
                result["present"] = True
                result["nexthops"] = [nh.get("ip") for nh in nexthops if "ip" in nh]
                if len(result["nexthops"]) >= 2:
                    result["multipath"] = True
    except Exception as e:
        result["error"] = str(e)
    return result


def test_ping(client_container: str, target_ip: str, count: int = 10) -> int:
    """Sends ICMP echo requests and returns number of successful replies."""
    rc, out, _ = run_cmd(["docker", "exec", client_container, "ping", "-c", str(count), "-W", "1", target_ip])
    match = re.search(r"(\d+)\s+(?:packets\s+)?received", out)
    if match:
        return int(match.group(1))
    return count if rc == 0 else 0


def record_evidence(run_type: str, bgp_matrix: dict, ecmp_status: dict, pings: dict, success: bool, notes: str = ""):
    os.makedirs(os.path.dirname(EVIDENCE_FILE), exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_type": run_type,
        "assertions": {
            "bgp_sessions": bgp_matrix,
            "ecmp_status": ecmp_status,
            "client1_to_client2_pings": pings.get("c1_to_c2", 0),
            "client2_to_client1_pings": pings.get("c2_to_c1", 0),
            "total_pings": pings.get("total", 20)
        },
        "success": success,
        "notes": notes
    }
    with open(EVIDENCE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    print(f"\n[+] Evidence saved to: {EVIDENCE_FILE}")
    return record


def main():
    parser = argparse.ArgumentParser(description="CLOS Fabric Assertion Engine")
    parser.add_argument("--run_type", default="spine_leaf_baseline", help="Run label")
    args = parser.parse_args()

    print("=================================================================")
    print("   NetOps-SLM Phase 2: CLOS Spine-Leaf Fabric Health Engine      ")
    print("=================================================================")

    # 1. Check all BGP sessions
    bgp_expectations = {
        "leaf-1 -> spine-1 (10.77.0.2)": (LEAF_1, "10.77.0.2"),
        "leaf-1 -> spine-2 (10.77.0.6)": (LEAF_1, "10.77.0.6"),
        "leaf-2 -> spine-1 (10.77.0.10)": (LEAF_2, "10.77.0.10"),
        "leaf-2 -> spine-2 (10.77.0.14)": (LEAF_2, "10.77.0.14"),
        "spine-1 -> leaf-1 (10.77.0.1)": (SPINE_1, "10.77.0.1"),
        "spine-1 -> leaf-2 (10.77.0.9)": (SPINE_1, "10.77.0.9"),
        "spine-2 -> leaf-1 (10.77.0.5)": (SPINE_2, "10.77.0.5"),
        "spine-2 -> leaf-2 (10.77.0.13)": (SPINE_2, "10.77.0.13"),
    }

    print("\n[*] Checking BGP Session States:")
    bgp_matrix = {}
    all_bgp_up = True
    for desc, (cname, ip) in bgp_expectations.items():
        is_up = check_bgp_peer(cname, ip)
        bgp_matrix[desc] = is_up
        status_sym = "[OK]" if is_up else "[FAIL]"
        print(f"  {status_sym} {desc}: {'Established' if is_up else 'Down/Idle'}")
        if not is_up:
            all_bgp_up = False

    # 2. Check ECMP on leaf switches
    print("\n[*] Checking ECMP Multipath Routes:")
    leaf1_ecmp = check_ecmp_route(LEAF_1, "10.77.2.0/24")
    leaf2_ecmp = check_ecmp_route(LEAF_2, "10.77.1.0/24")

    print(f"  Leaf-1 ECMP to 10.77.2.0/24: present={leaf1_ecmp['present']}, multipath={leaf1_ecmp['multipath']}, nexthops={leaf1_ecmp.get('nexthops')}")
    print(f"  Leaf-2 ECMP to 10.77.1.0/24: present={leaf2_ecmp['present']}, multipath={leaf2_ecmp['multipath']}, nexthops={leaf2_ecmp.get('nexthops')}")

    ecmp_ok = leaf1_ecmp["multipath"] and leaf2_ecmp["multipath"]

    # 3. Test Data Plane ICMP Reachability
    print("\n[*] Testing Data Plane Reachability:")
    c1_c2 = test_ping(CLIENT_1, "10.77.2.10", count=10)
    c2_c1 = test_ping(CLIENT_2, "10.77.1.10", count=10)
    print(f"  client-1 -> client-2: {c1_c2}/10 replies")
    print(f"  client-2 -> client-1: {c2_c1}/10 replies")

    pings_ok = (c1_c2 >= 9) and (c2_c1 >= 9)
    overall_success = all_bgp_up and ecmp_ok and pings_ok

    print("\n-----------------------------------------------------------------")
    print(f"BGP Control Plane : {'PASSED' if all_bgp_up else 'FAILED'}")
    print(f"ECMP Multi-Path   : {'PASSED (2 Nexthops Active)' if ecmp_ok else 'FAILED'}")
    print(f"Data Plane Reach  : {'PASSED' if pings_ok else 'FAILED'}")
    print(f"OVERALL RESULT    : {'ALL ASSERTIONS PASSED [PASS]' if overall_success else 'ASSERTION FAILURE [FAIL]'}")
    print("-----------------------------------------------------------------")

    record_evidence(
        run_type=args.run_type,
        bgp_matrix=bgp_matrix,
        ecmp_status={"leaf1": leaf1_ecmp, "leaf2": leaf2_ecmp},
        pings={"c1_to_c2": c1_c2, "c2_to_c1": c2_c1, "total": 20},
        success=overall_success,
        notes="Automated baseline validation for 4-Node Spine-Leaf CLOS Fabric"
    )

    sys.exit(0 if overall_success else 1)


if __name__ == "__main__":
    main()
