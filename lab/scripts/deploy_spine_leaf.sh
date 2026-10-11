#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_DIR="$(dirname "$SCRIPT_DIR")"

echo "[*] Deploying Phase 2 4-Node Spine-Leaf CLOS Fabric using Containerlab..."
containerlab deploy -t "${LAB_DIR}/topology_spine_leaf.clab.yml" --reconfigure
echo "[+] Fabric deployed successfully. Waiting 12s for BGP peering & ECMP convergence..."
sleep 12
python3 "${SCRIPT_DIR}/verify_spine_leaf.py"
