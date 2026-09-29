#!/usr/bin/env bash
set -euo pipefail

CONTAINER="clab-netops-bgp-lab-router-a"
NEIGHBOR="10.77.0.2"
ASN="65001"

echo "[*] Executing Deterministic Runbook: Re-enabling BGP neighbor ${NEIGHBOR} on ${CONTAINER}..."
docker exec "${CONTAINER}" vtysh \
  -c "configure terminal" \
  -c "router bgp ${ASN}" \
  -c "no neighbor ${NEIGHBOR} shutdown"

echo "[+] Remediation applied at $(date -u +"%Y-%m-%dT%H:%M:%SZ"). Waiting 8s for session re-establishment..."
sleep 8
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "${SCRIPT_DIR}/verify_health.py"
