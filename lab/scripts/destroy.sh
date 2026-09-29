#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_DIR="$(dirname "$SCRIPT_DIR")"

echo "[-] Destroying NetOps BGP Lab and cleaning up..."
containerlab destroy -t "${LAB_DIR}/topology.clab.yml" --cleanup
echo "[+] Cleanup complete."
