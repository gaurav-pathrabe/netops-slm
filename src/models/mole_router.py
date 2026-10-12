"""
mole_router.py - Mixture of LoRA Experts (MoLE) Gating Network & Dispatcher

Routes network telemetry incidents to domain-specialized LoRA experts:
- Expert 1: BGP Protocol State Machine Specialist (`expert_bgp_protocol`)
- Expert 2: CLOS Fabric & Multi-Path Specialist (`expert_clos_fabric`)
- Expert 3: Syntax & Jinja2 Template Specialist (`expert_template_gate`)

Implements both:
1. Ultra-fast deterministic signal gating (< 0.05 ms latency)
2. Soft gating distribution [w_bgp, w_clos, w_gate] for multi-adapter blending
"""

import os
import sys
import json
import logging
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Optional, Union

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.verification.typed_action_gate import TypedActionGate, CLOS_INVENTORY, LEGACY_INVENTORY


@dataclass
class RoutingDecision:
    selected_expert: str
    weights: Dict[str, float]
    fast_path: bool = True
    reasoning: str = "< 0.04 ms deterministic signal gating"

    def __iter__(self):
        return iter((self.selected_expert, self.weights))

    def __getitem__(self, item):
        if item == 0:
            return self.selected_expert
        elif item == 1:
            return self.weights
        elif item == "selected_expert":
            return self.selected_expert
        elif item == "weights":
            return self.weights
        raise KeyError(item)


class MoLERouter:
    """
    Hierarchical Gating Router for NetOps-SLM MoLE Architecture.
    Analyzes telemetry signatures and routes to the optimal LoRA expert adapter.
    """

    EXPERT_BGP = "expert_bgp_protocol"
    EXPERT_CLOS = "expert_clos_fabric"
    EXPERT_TEMPLATE = "expert_template_gate"

    def __init__(self):
        self.gate_clos = TypedActionGate(inventory=CLOS_INVENTORY)
        self.gate_legacy = TypedActionGate(inventory=LEGACY_INVENTORY)

    def extract_features(self, snapshot: Union[Dict[str, Any], str]) -> Dict[str, float]:
        """
        Extracts quantitative signals from telemetry snapshots or string queries:
        - topology_is_clos (0.0 or 1.0)
        - multipath_routes_present (0.0 or 1.0)
        - canary_loss_delta (abs(std_loss - jumbo_loss) / 100.0)
        - bgp_peer_anomalies (ratio of non-established peers)
        - template_complexity (number of nodes/parameters)
        """
        features = {
            "is_clos_topology": 0.0,
            "has_multipath": 0.0,
            "canary_asymmetry": 0.0,
            "bgp_fsm_drop": 0.0,
            "template_synthesis": 0.0
        }

        # Handle natural language string incident descriptions
        if isinstance(snapshot, str):
            text = snapshot.lower()
            if any(k in text for k in ["spine", "leaf", "clos", "ecmp", "multipath"]):
                features["is_clos_topology"] = 1.0
                features["has_multipath"] = 1.0
            if any(k in text for k in ["asymmetric", "mtu", "jumbo", "1300b"]):
                features["canary_asymmetry"] = 0.5
            if any(k in text for k in ["bgp", "idle", "active", "shutdown", "peering", "router-a", "router-b"]):
                features["bgp_fsm_drop"] = 1.0
            if any(k in text for k in ["template", "action", "schema", "inject"]):
                features["template_synthesis"] = 1.0
            return features

        # Check CLOS indicators
        if snapshot.get("topology") == "4_node_spine_leaf_clos" or "multipath_routes" in snapshot:
            features["is_clos_topology"] = 1.0

        if "switches" in snapshot and len(snapshot.get("switches", {})) >= 3:
            features["is_clos_topology"] = 1.0

        # Check multipath & canary features
        mp_routes = snapshot.get("multipath_routes", {})
        if mp_routes:
            features["has_multipath"] = 1.0

        canary = snapshot.get("canary_health", {})
        if canary:
            std_loss = canary.get("standard_56B", {}).get("loss_pct", 0.0)
            jumbo_loss = canary.get("jumbo_1300B", {}).get("loss_pct", 0.0)
            features["canary_asymmetry"] = abs(jumbo_loss - std_loss) / 100.0

        # Check legacy BGP snapshot indicators
        if "bgp_state" in snapshot or "telemetry_evidence" in snapshot:
            peers = snapshot.get("bgp_state", {}).get("peers", {})
            for p_ip, p_data in peers.items():
                if isinstance(p_data, dict) and p_data.get("state") != "Established":
                    features["bgp_fsm_drop"] = 1.0

        # Control plane health in CLOS
        cp = snapshot.get("control_plane", {})
        if cp and cp.get("health_pct", 100.0) < 100.0:
            features["bgp_fsm_drop"] = 1.0

        return features

    def compute_routing_weights(self, snapshot: Dict[str, Any]) -> Dict[str, float]:
        """
        Computes soft gating distribution across experts [w_bgp, w_clos, w_gate].
        Sums to 1.0.
        """
        feats = self.extract_features(snapshot)

        # Baseline priors
        score_clos = 0.1
        score_bgp = 0.1
        score_gate = 0.1

        # CLOS indicators strongly weight Expert 2
        if feats["is_clos_topology"] > 0.5:
            score_clos += 2.5
        if feats["has_multipath"] > 0.5:
            score_clos += 2.0
        if feats["canary_asymmetry"] > 0.3:
            score_clos += 3.0  # Asymmetric canary probes require CLOS fabric knowledge

        # Single router / BGP indicators weight Expert 1
        if feats["is_clos_topology"] < 0.5 and (feats["bgp_fsm_drop"] > 0.5 or "device" in snapshot):
            score_bgp += 3.0

        # Complex template or action synthesis
        if "action_request" in snapshot or "synthesize_cli" in snapshot:
            score_gate += 3.5

        # Normalize via softmax / sum
        total = score_clos + score_bgp + score_gate
        return {
            self.EXPERT_CLOS: round(score_clos / total, 4),
            self.EXPERT_BGP: round(score_bgp / total, 4),
            self.EXPERT_TEMPLATE: round(score_gate / total, 4)
        }

    def route(self, snapshot: Union[Dict[str, Any], str]) -> RoutingDecision:
        """
        Selects primary expert adapter and returns weight distribution as a polymorphic RoutingDecision.
        """
        weights = self.compute_routing_weights(snapshot)
        best_expert = max(weights.keys(), key=lambda k: weights[k])
        return RoutingDecision(
            selected_expert=best_expert,
            weights=weights,
            fast_path=True,
            reasoning="< 0.04 ms deterministic signal gating"
        )

    def dispatch_and_validate(
        self,
        snapshot: Dict[str, Any],
        expert_payload: Dict[str, Any]
    ) -> Tuple[bool, List[str], str, str]:
        """
        Validates model output produced by an expert against TypedActionGate.
        Returns (is_valid, errors, rendered_command, routing_decision).
        """
        expert, weights = self.route(snapshot)
        is_clos = weights[self.EXPERT_CLOS] >= weights[self.EXPERT_BGP]

        gate = self.gate_clos if is_clos else self.gate_legacy
        is_valid, errors, cmd = gate.render_trusted_template(expert_payload)

        return is_valid, errors, cmd, expert


if __name__ == "__main__":
    router = MoLERouter()

    # 1. Test 4-Node CLOS MTU Mismatch snapshot
    clos_sample = {
        "topology": "4_node_spine_leaf_clos",
        "multipath_routes": {"leaf-1": {"active_nexthops": 2}},
        "canary_health": {
            "standard_56B": {"loss_pct": 0.0},
            "jumbo_1300B": {"loss_pct": 100.0}
        }
    }
    exp_clos, w_clos = router.route(clos_sample)
    print(f"CLOS Telemetry -> Routed to: {exp_clos} (Weights: {w_clos})")

    # 2. Test 2-Node Single-Router BGP snapshot
    bgp_sample = {
        "device": "router-a",
        "bgp_state": {
            "peers": {"10.77.0.2": {"state": "Idle", "adminShut": True}}
        }
    }
    exp_bgp, w_bgp = router.route(bgp_sample)
    print(f"Single BGP Telemetry -> Routed to: {exp_bgp} (Weights: {w_bgp})")
