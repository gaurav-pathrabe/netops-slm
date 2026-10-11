#!/usr/bin/env python3
"""
run_clos_batch.py - Automated Batch Capture for CLOS Fault Taxonomy

Executes a complete sweep across all 5 CLOS fault scenarios:
1. EPISODE_CLOS_001_CONTROL (Healthy baseline)
2. EPISODE_CLOS_002_LINK_SEVERED (Physical wire cut on spine-1)
3. EPISODE_CLOS_003_MTU_MISMATCH (Asymmetric MTU clamping on spine-1)
4. EPISODE_CLOS_004_ROUTE_BLACKHOLE (Hash-polarized ECMP silent drop)
5. EPISODE_CLOS_005_OPTICAL_FLAP (Flapping transceiver - Invariant 1 trigger)

Produces authentic datasets in logs/raw/ with zero synthetic fabrication.
"""

import os
import sys
import time
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RECORDER_SCRIPT = os.path.join(SCRIPT_DIR, "record_clos_episode.py")
VERIFY_SCRIPT = os.path.join(SCRIPT_DIR, "verify_spine_leaf.py")

CLOS_SWEEP = [
    ("EPISODE_CLOS_001_CONTROL", "CLOS_HEALTHY_CONTROL"),
    ("EPISODE_CLOS_002_LINK_SEVERED", "CLOS_SPINE_LINK_SEVERED"),
    ("EPISODE_CLOS_003_MTU_MISMATCH", "CLOS_ASYMMETRIC_MTU_MISMATCH"),
    ("EPISODE_CLOS_004_ROUTE_BLACKHOLE", "CLOS_ECMP_ROUTE_BLACKHOLE"),
    ("EPISODE_CLOS_005_OPTICAL_FLAP", "CLOS_OPTICAL_FLAP"),
]


def main():
    print("=================================================================")
    print("   NetOps-SLM Phase 3: CLOS 5-Incident Authentic Sweep Batch     ")
    print("=================================================================")

    # 1. Pre-flight health verification
    print("\n[*] Pre-Flight Health Assertion on Live Fabric...")
    rc = subprocess.run([sys.executable, VERIFY_SCRIPT], capture_output=True, text=True).returncode
    if rc != 0:
        print("[-] Error: Fabric is not in healthy baseline state. Run deploy_spine_leaf.sh first.")
        sys.exit(1)
    print("[+] Fabric verified 100% healthy. Starting automated sweep...\n")

    # 2. Iterate through fault sweep
    results = []
    for ep_id, fault in CLOS_SWEEP:
        print(f"-----------------------------------------------------------------")
        print(f"--> Capturing: {ep_id} ({fault})")
        print(f"-----------------------------------------------------------------")
        res = subprocess.run([
            sys.executable, RECORDER_SCRIPT,
            "--episode_id", ep_id,
            "--fault", fault
        ])
        results.append((ep_id, fault, res.returncode == 0))
        time.sleep(3)

    # 3. Final Health Assertion
    print("\n[*] Post-Flight Health Assertion on Restored Fabric...")
    rc_final = subprocess.run([sys.executable, VERIFY_SCRIPT], capture_output=True, text=True).returncode
    print(f"[+] Post-Flight Verification: {'PASSED [OK]' if rc_final == 0 else 'FAILED [WARN]'}")

    print("\n=================================================================")
    print("                   CLOS BATCH SUMMARY LEDGER                     ")
    print("=================================================================")
    for ep_id, fault, success in results:
        status_sym = "[SUCCESS]" if success else "[FAILED]"
        print(f"  {status_sym} {ep_id}: {fault}")
    print("=================================================================")


if __name__ == "__main__":
    main()
