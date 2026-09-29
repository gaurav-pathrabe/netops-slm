#!/usr/bin/env bash
set -euo pipefail

CONTAINER="clab-netops-bgp-lab-router-a"
NEIGHBOR="10.77.0.2"
ASN="65001"

echo "[!] Injecting Fault: Administratively shutting down BGP neighbor ${NEIGHBOR} on ${CONTAINER}..."
docker exec "${CONTAINER}" vtysh \
  -c "configure terminal" \
  -c "router bgp ${ASN}" \
  -c "neighbor ${NEIGHBOR} shutdown"

echo "[+] Fault injection executed at $(date -u +"%Y-%m-%dT%H:%M:%SZ")."
echo "[*] Capturing post-fault router state..."
docker exec "${CONTAINER}" vtysh -c "show ip bgp summary"
