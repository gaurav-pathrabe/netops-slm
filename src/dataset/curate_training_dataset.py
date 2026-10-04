"""
curate_training_dataset.py - Authentic Lab Episode Dataset Curator

Curates training, validation, and test datasets EXCLUSIVELY from authentic
observations downloaded from live FRR lab containers in `logs/raw/<episode_id>/`.
Adheres to NetOps-SLM Milestone 2 & Milestone 4 requirements:
- Zero synthetic Cisco logs.
- Outputs strict typed JSON schema conforming to TypedActionGate.
- Partitions datasets into train, validation, and test sets.
"""

import os
import sys
import json
import logging
from typing import Dict, Any, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.telemetry.frr_telemetry_collector import FRRTelemetryCollector

SYSTEM_PROMPT = (
    "You are NetOps-SLM, an evidence-based network diagnosis engine for FRRouting environments.\n"
    "Given an authentic incident telemetry snapshot, analyze the logs and routing state.\n"
    "You MUST respond ONLY with valid JSON conforming to this schema:\n"
    "{\n"
    '  "diagnosis": "<string>",\n'
    '  "evidence_ids": ["<id>"],\n'
    '  "affected_nodes": ["<device>"],\n'
    '  "action": "reenable_bgp_neighbor" | "correct_remote_as" | "originate_prefix" | "none",\n'
    '  "parameters": {"device": "<device>", "neighbor": "<ip>", "expected_remote_as": <int>, "prefix": "<cidr>"},\n'
    '  "verification_checks": ["bgp_session", "expected_routes", "endpoint_ping"],\n'
    '  "abstain": true | false\n'
    "}\n"
    "Rules:\n"
    "- If the network is healthy, abstain must be true and action must be 'none'.\n"
    "- If the failure is ambiguous or outside authorized lab inventory, abstain must be true.\n"
    "- Never output raw shell commands."
)



def load_raw_lab_episodes(raw_dir: str) -> List[Dict[str, Any]]:
    """Scans logs/raw/ for authentic episodes downloaded from running lab containers."""
    if not os.path.exists(raw_dir):
        logging.warning(f"Raw logs directory {raw_dir} does not exist yet.")
        return []

    episodes = []
    collector = FRRTelemetryCollector()

    for item in sorted(os.listdir(raw_dir)):
        ep_path = os.path.join(raw_dir, item)
        if not os.path.isdir(ep_path):
            continue

        meta_file = os.path.join(ep_path, "injection_metadata.json")
        log_file = os.path.join(ep_path, "frr.log")
        bgp_file = os.path.join(ep_path, "bgp_state.json")

        if not os.path.exists(meta_file):
            continue

        with open(meta_file, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        # Parse real FRR log lines
        parsed_events = []
        if os.path.exists(log_file):
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        ev = collector.parse_line(line, device=metadata.get("target_device", "router-a"))
                        if ev.get("parsed"):
                            parsed_events.append(ev)

        # Load live BGP state
        bgp_state = {}
        if os.path.exists(bgp_file):
            try:
                with open(bgp_file, "r", encoding="utf-8") as f:
                    bgp_state = json.load(f)
            except Exception:
                pass

        snapshot = collector.group_events_into_snapshot(
            events=parsed_events,
            bgp_state=bgp_state,
            device=metadata.get("target_device", "router-a")
        )

        episodes.append({
            "metadata": metadata,
            "snapshot": snapshot,
            "episode_id": metadata.get("episode_id", item)
        })

    logging.info(f"Loaded {len(episodes)} authentic lab episodes from {raw_dir}.")
    return episodes


def generate_ground_truth_target(metadata: Dict[str, Any], snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Generates the verified ground-truth typed action based on the lab injection record."""
    fault = metadata.get("ground_truth_fault")
    device = metadata.get("target_device", "router-a")
    peer = metadata.get("peer_ip", "10.77.0.2")

    events = snapshot.get("telemetry_evidence", [])
    ev_ids = [e["id"] for e in events] if events else ["state_snapshot"]

    if fault == "bgp_neighbor_admin_shutdown":
        return {
            "diagnosis": "bgp_neighbor_admin_shutdown",
            "evidence_ids": ev_ids,
            "affected_nodes": [device],
            "action": "reenable_bgp_neighbor",
            "parameters": {
                "device": device,
                "neighbor": peer
            },
            "verification_checks": ["bgp_session", "expected_routes", "endpoint_ping"],
            "abstain": False
        }
    elif fault == "healthy_network":
        return {
            "diagnosis": "healthy_network",
            "evidence_ids": ["state_snapshot"],
            "affected_nodes": [device],
            "action": "none",
            "parameters": {"device": device},
            "verification_checks": ["bgp_session"],
            "abstain": True
        }
    elif fault == "incorrect_remote_as":
        return {
            "diagnosis": "bgp_bad_peer_as_mismatch",
            "evidence_ids": ev_ids,
            "affected_nodes": [device],
            "action": "correct_remote_as",
            "parameters": {
                "device": device,
                "neighbor": peer,
                "expected_remote_as": 65002 if device == "router-a" else 65001
            },
            "verification_checks": ["bgp_session", "expected_routes", "endpoint_ping"],
            "abstain": False
        }
    elif fault == "missing_prefix_origination":
        return {
            "diagnosis": "missing_prefix_origination",
            "evidence_ids": ev_ids,
            "affected_nodes": [device],
            "action": "originate_prefix",
            "parameters": {
                "device": device,
                "prefix": "10.77.1.0/24"
            },
            "verification_checks": ["bgp_session", "expected_routes", "endpoint_ping"],
            "abstain": False
        }
    elif fault == "transport_failure":
        return {
            "diagnosis": "transport_carrier_loss",
            "evidence_ids": ev_ids,
            "affected_nodes": [device],
            "action": "none",
            "parameters": {"device": device},
            "verification_checks": [],
            "abstain": True
        }
    else:
        return {
            "diagnosis": "unknown_fault",
            "evidence_ids": ev_ids,
            "affected_nodes": [device],
            "action": "none",
            "parameters": {"device": device},
            "verification_checks": [],
            "abstain": True
        }


def format_sharegpt_example(episode: Dict[str, Any]) -> Dict[str, Any]:
    """Converts authentic snapshot and verified solution into standard ShareGPT/ChatML format."""
    meta = episode["metadata"]
    snap = episode["snapshot"]
    target = generate_ground_truth_target(meta, snap)

    return {
        "conversations": [
            {"from": "system", "value": SYSTEM_PROMPT},
            {"from": "human", "value": json.dumps(snap, indent=2)},
            {"from": "gpt", "value": json.dumps(target, indent=2)}
        ],
        "metadata": meta
    }


def curate_datasets(raw_dir: str, output_dir: str):
    """Generates train, validation, and test datasets from authentic container captures."""
    import random
    episodes = load_raw_lab_episodes(raw_dir)
    os.makedirs(output_dir, exist_ok=True)

    if not episodes:
        print(f"[*] No authentic episodes found in {raw_dir}. Capture episodes using lab/scripts/record_episode.py first.")
        return

    dataset_examples = [format_sharegpt_example(ep) for ep in episodes]

    # Save full manifest
    manifest_path = os.path.join(output_dir, "manifest.jsonl")
    with open(manifest_path, "w", encoding="utf-8") as f:
        for ex in dataset_examples:
            f.write(json.dumps(ex) + "\n")

    # Split into train (50%), val (25%), test (25%)
    random.seed(42)
    shuffled = list(dataset_examples)
    random.shuffle(shuffled)
    n = len(shuffled)
    n_train = max(1, int(n * 0.5))
    n_val = max(1, int(n * 0.25))

    train_set = shuffled[:n_train]
    val_set = shuffled[n_train:n_train + n_val]
    test_set = shuffled[n_train + n_val:]
    if not test_set:
        test_set = val_set

    for name, subset in [("train.jsonl", train_set), ("validation.jsonl", val_set), ("test.jsonl", test_set)]:
        path = os.path.join(output_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            for item in subset:
                f.write(json.dumps(item) + "\n")
        print(f"[+] Wrote {len(subset)} episodes to {path}")

    print(f"[+] Successfully curated {len(dataset_examples)} authentic examples into {output_dir}")


if __name__ == "__main__":
    raw_path = os.path.join(PROJECT_ROOT, "logs", "raw")
    dataset_out = os.path.join(PROJECT_ROOT, "dataset")
    curate_datasets(raw_path, dataset_out)
