"""
test_model_adapter.py - Unit test suite for the Model Adapter Boundary

Validates:
1. CompactObservationFormatter (no token-soup, clean typed dicts)
2. FrontierAPIAdapter and LocalDenseAdapter execution
3. GoverningGateEvaluator against the 3 non-negotiable safety rules
"""

import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.models.model_adapter import (
    CompactObservationFormatter,
    FrontierAPIAdapter,
    LocalDenseAdapter,
    NarrowClassifierAdapter,
    GoverningGateEvaluator
)


def test_compact_observation_formatter():
    print("[*] 1. Testing CompactObservationFormatter...")
    raw_vtysh = {
        "routerId": "10.77.0.1",
        "as": 65001,
        "peers": {
            "10.77.0.2": {
                "remoteAs": 65002,
                "state": "Established",
                "peerUptime": "01:24:12",
                "pfxRcvd": 4
            }
        }
    }
    compact_bgp = CompactObservationFormatter.format_bgp_summary(raw_vtysh)
    assert compact_bgp["local_as"] == 65001
    assert len(compact_bgp["peers"]) == 1
    assert compact_bgp["peers"][0]["peer"] == "10.77.0.2"
    assert compact_bgp["peers"][0]["state"] == "Established"

    raw_counters = {
        "eth1": {"carrier": True, "mtu": 1200, "rx_errors": 0, "crc_errors": 0, "speed": 10000}
    }
    compact_iface = CompactObservationFormatter.format_interface_counters(raw_counters)
    assert compact_iface["eth1"]["mtu"] == 1200
    assert compact_iface["eth1"]["carrier"] is True

    print("    [+] Compact Observation Formatter eliminates token-soup successfully.")


def test_adapters_and_governing_rule():
    print("\n[*] 2. Testing Model Adapters and Governing Decision Rule...")
    frontier = FrontierAPIAdapter(model_name="claude-3-5-sonnet")
    dense = LocalDenseAdapter(model_name="qwen-2.5-14b-awq")

    # Evaluation episode for MTU mismatch
    eval_episodes = [
        {
            "telemetry": {
                "ping": {"small_payload_loss_pct": 0.0, "jumbo_payload_loss_pct": 100.0},
                "bgp": {"peers": [{"peer": "10.77.0.2", "state": "Established"}]}
            },
            "ground_truth": {"fault_class": "CLOS_ASYMMETRIC_MTU_MISMATCH"}
        },
        {
            "telemetry": {
                "ping": {"small_payload_loss_pct": 0.0, "jumbo_payload_loss_pct": 0.0},
                "bgp": {"peers": [{"peer": "10.77.0.2", "state": "Established"}]}
            },
            "ground_truth": {"fault_class": "BENIGN_TRANSIENT_SPIKE"}
        }
    ]

    frontier_eval = GoverningGateEvaluator.evaluate_model_candidate(frontier, eval_episodes)
    print(f"    - Frontier Eval: Top3={frontier_eval['top3_accuracy']*100:.1f}%, Faithfulness={frontier_eval['evidence_faithfulness']*100:.1f}%, Unsafe={frontier_eval['unsafe_action_rate']*100:.1f}%")
    assert frontier_eval["governing_gate_passed"] is True, "Frontier adapter must pass governing gate"

    dense_eval = GoverningGateEvaluator.evaluate_model_candidate(dense, eval_episodes)
    print(f"    - Local Dense Eval: Top3={dense_eval['top3_accuracy']*100:.1f}%, Faithfulness={dense_eval['evidence_faithfulness']*100:.1f}%, Unsafe={dense_eval['unsafe_action_rate']*100:.1f}%")
    assert dense_eval["governing_gate_passed"] is True, "Local dense adapter must pass governing gate"

    print("    [+] All Model Adapters passed Governing Gate Evaluation.")


if __name__ == "__main__":
    test_compact_observation_formatter()
    test_adapters_and_governing_rule()
    print("\n=======================================================")
    print("      ALL MODEL ADAPTER BOUNDARY TESTS PASSED          ")
    print("=======================================================")
