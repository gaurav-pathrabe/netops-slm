#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_DIR="$(dirname "$SCRIPT_DIR")"

echo "[*] Deploying NetOps BGP Lab using Containerlab..."
containerlab deploy -t "${LAB_DIR}/topology.clab.yml" --reconfigure
echo "[+] Lab deployed successfully. Waiting 10s for BGP convergence..."
sleep 10
python3 "${SCRIPT_DIR}/verify_health.py"
