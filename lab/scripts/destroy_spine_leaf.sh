#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_DIR="$(dirname "$SCRIPT_DIR")"

echo "[*] Destroying Phase 2 Spine-Leaf Fabric..."
containerlab destroy -t "${LAB_DIR}/topology_spine_leaf.clab.yml" --cleanup
echo "[+] Spine-Leaf lab cleaned up."
