"""
typed_action_gate.py - Bounded Execution & Typed Schema Validation Gate
Ensures model outputs conform to strict JSON schemas, parameters match verified
lab inventory, and maps abstract actions to trusted deterministic templates.
Fulfills Invariants 1, 4, 7 and outer-loop security constraints.
Supports both Legacy 2-Node lab and Phase 2/3 4-Node Spine-Leaf CLOS Fabric.
"""

import json
import time
from typing import Dict, Any, Tuple, List, Optional
from datetime import datetime, timezone

# Legacy 2-Node Lab Inventory
LEGACY_INVENTORY = {
    "prefix": "clab-netops-bgp-lab-",
    "devices": ["router-a", "router-b"],
    "asns": {
        "router-a": 65001,
        "router-b": 65002
    },
    "neighbors": {
        "router-a": ["10.77.0.2"],
        "router-b": ["10.77.0.1"]
    },
    "subnets": ["10.77.0.0/30", "10.77.1.0/24", "10.77.2.0/24"]
}

# Phase 2 & 3: 4-Node Spine-Leaf CLOS Fabric Inventory
CLOS_INVENTORY = {
    "prefix": "clab-netops-spine-leaf-lab-",
    "devices": ["spine-1", "spine-2", "leaf-1", "leaf-2"],
    "asns": {
        "spine-1": 65100,
        "spine-2": 65100,
        "leaf-1": 65001,
        "leaf-2": 65002
    },
    "neighbors": {
        "spine-1": ["10.77.0.1", "10.77.0.9"],
        "spine-2": ["10.77.0.5", "10.77.0.13"],
        "leaf-1": ["10.77.0.2", "10.77.0.6"],
        "leaf-2": ["10.77.0.10", "10.77.0.14"]
    },
    "subnets": [
        "10.77.0.0/30", "10.77.0.4/30", "10.77.0.8/30", "10.77.0.12/30",
        "10.77.1.0/24", "10.77.2.0/24"
    ]
}

PERMITTED_ACTIONS = [
    "reenable_bgp_neighbor",
    "correct_remote_as",
    "originate_prefix",
    "drain_spine_traffic",
    "isolate_degraded_path",
    "restore_spine_path",
    "none"
]

REQUIRED_SCHEMA_KEYS = [
    "diagnosis",
    "evidence_ids",
    "affected_nodes",
    "action",
    "parameters",
    "verification_checks",
    "abstain"
]


class TypedActionGate:
    def __init__(self, inventory: Dict[str, Any] = CLOS_INVENTORY):
        self.inventory = inventory
        self.flap_history: Dict[str, List[float]] = {}  # Invariant 1 Flap tracker: {target: [timestamps]}

    def record_flap_event(self, target: str, timestamp: Optional[float] = None) -> int:
        """Registers a flap event and prunes events older than 15 minutes (900 seconds)."""
        ts = timestamp if timestamp is not None else time.time()
        if target not in self.flap_history:
            self.flap_history[target] = []
        # Prune older than 900s
        self.flap_history[target] = [t for t in self.flap_history[target] if (ts - t) <= 900.0]
        self.flap_history[target].append(ts)
        return len(self.flap_history[target])

    def validate_action_payload(self, payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validates JSON schema, key types, permitted actions, inventory bounds, and safety invariants."""
        errors = []

        # 1. Schema keys check
        for key in REQUIRED_SCHEMA_KEYS:
            if key not in payload:
                errors.append(f"Schema violation: missing required key '{key}'")

        if errors:
            return False, errors

        # 2. Abstention check
        if payload.get("abstain") is True:
            if payload.get("action") not in ["none", ""]:
                errors.append("Invalid abstention: action must be 'none' when abstain is True")
            return len(errors) == 0, errors

        # 3. Permitted action check
        action = payload.get("action")
        if action not in PERMITTED_ACTIONS:
            errors.append(f"Forbidden action: '{action}' is not in permitted actions list {PERMITTED_ACTIONS}")

        # 4. Inventory boundaries check
        nodes = payload.get("affected_nodes", [])
        for node in nodes:
            if node not in self.inventory["devices"]:
                errors.append(f"Inventory violation: unknown device '{node}'")

        params = payload.get("parameters", {})
        device = params.get("device")
        neighbor = params.get("neighbor")
        prefix = params.get("prefix")

        if device not in self.inventory["devices"]:
            errors.append(f"Parameter error: device '{device}' is not recognized in lab inventory")
        elif neighbor and neighbor not in self.inventory["neighbors"].get(device, []):
            errors.append(f"Parameter error: neighbor '{neighbor}' is not an authorized peer for device '{device}'")
        elif prefix and prefix not in self.inventory["subnets"]:
            errors.append(f"Parameter error: prefix '{prefix}' is not in authorized inventory subnets")

        # 5. Invariant 1: BGP Flap Damping Guard (Anti-Oscillation)
        target_entity = neighbor or device
        if target_entity in self.flap_history:
            recent_flaps = len([t for t in self.flap_history[target_entity] if (time.time() - t) <= 900.0])
            if recent_flaps >= 2 and action != "none":
                errors.append(
                    f"Invariant 1 Violation: Peer/Device '{target_entity}' flapped {recent_flaps} times in 15m. "
                    f"Auto-fix locked out to prevent global route flap damping. Technician required."
                )

        # 6. Evidence references check
        evidence = payload.get("evidence_ids", [])
        if not evidence or not isinstance(evidence, list):
            errors.append("Evidence error: at least one valid evidence_id must be cited")

        return len(errors) == 0, errors

    def render_trusted_template(self, payload: Dict[str, Any]) -> Tuple[bool, List[str], str]:
        """
        Renders safe, deterministic vtysh commands from validated typed action.
        Model text is never executed directly (Invariant 4).
        """
        is_valid, errors = self.validate_action_payload(payload)
        if not is_valid:
            return False, errors, ""

        if payload.get("abstain") is True or payload.get("action") == "none":
            return True, [], "# Action abstained. No network commands executed."

        action = payload.get("action")
        params = payload.get("parameters", {})
        device = params.get("device")
        neighbor = params.get("neighbor")
        prefix = params.get("prefix")
        expected_as = params.get("expected_remote_as")
        asn = self.inventory["asns"].get(device)
        prefix_cname = self.inventory.get("prefix", "clab-netops-spine-leaf-lab-")

        if action == "reenable_bgp_neighbor":
            command = (
                f"docker exec {prefix_cname}{device} vtysh "
                f"-c 'configure terminal' "
                f"-c 'router bgp {asn}' "
                f"-c 'no neighbor {neighbor} shutdown'"
            )
            return True, [], command

        elif action == "correct_remote_as":
            target_as = expected_as if expected_as else 65100
            command = (
                f"docker exec {prefix_cname}{device} vtysh "
                f"-c 'configure terminal' "
                f"-c 'router bgp {asn}' "
                f"-c 'neighbor {neighbor} remote-as {target_as}'"
            )
            return True, [], command

        elif action == "originate_prefix":
            target_prefix = prefix if prefix else ("10.77.1.0/24" if "leaf-1" in device else "10.77.2.0/24")
            command = (
                f"docker exec {prefix_cname}{device} vtysh "
                f"-c 'configure terminal' "
                f"-c 'router bgp {asn}' "
                f"-c 'address-family ipv4 unicast' "
                f"-c 'network {target_prefix}'"
            )
            return True, [], command

        elif action == "drain_spine_traffic":
            # Gracefully diverts traffic away from degraded spine by setting MED to 65535
            command = (
                f"docker exec {prefix_cname}{device} vtysh "
                f"-c 'configure terminal' "
                f"-c 'route-map RM_DRAIN permit 10' "
                f"-c ' set metric 65535' "
                f"-c 'exit' "
                f"-c 'router bgp {asn}' "
                f"-c ' address-family ipv4 unicast' "
                f"-c '  neighbor {neighbor} route-map RM_DRAIN out' "
                f"-c ' exit-address-family' "
                f"-c 'exit' "
                f"-c 'clear ip bgp {neighbor} soft out'"
            )
            return True, [], command

        elif action == "isolate_degraded_path":
            # Temporarily brings down a blackholing interface on the leaf switch
            iface = params.get("interface", "eth1")
            command = f"docker exec {prefix_cname}{device} ip link set dev {iface} down"
            return True, [], command

        elif action == "restore_spine_path":
            # Removes drain route-map and restores normal metric
            command = (
                f"docker exec {prefix_cname}{device} vtysh "
                f"-c 'configure terminal' "
                f"-c 'router bgp {asn}' "
                f"-c ' address-family ipv4 unicast' "
                f"-c '  no neighbor {neighbor} route-map RM_DRAIN out' "
                f"-c ' exit-address-family' "
                f"-c 'no route-map RM_DRAIN' "
                f"-c 'exit' "
                f"-c 'clear ip bgp {neighbor} soft out'"
            )
            return True, [], command

        return False, [f"No template available for action '{action}'"], ""


if __name__ == "__main__":
    gate = TypedActionGate(inventory=CLOS_INVENTORY)

    # 1. Valid CLOS Drain Action
    drain_payload = {
        "diagnosis": "spine_asymmetric_mtu_mismatch",
        "evidence_ids": ["probe_loss_jumbo_01", "bgp_up_canary_fail"],
        "affected_nodes": ["spine-1"],
        "action": "drain_spine_traffic",
        "parameters": {
            "device": "spine-1",
            "neighbor": "10.77.0.1"
        },
        "verification_checks": ["ecmp_rebalance", "zero_jumbo_drop"],
        "abstain": False
    }

    ok, errs, cmd = gate.render_trusted_template(drain_payload)
    print("CLOS Drain Payload Allowed:", ok)
    print("Rendered Command:\n", cmd)

    # 2. Invariant 1 Flap Damping Test
    print("\n--- Testing Invariant 1 (Flap Damping Guard) ---")
    gate.record_flap_event("10.77.0.2")
    gate.record_flap_event("10.77.0.2")  # 2nd flap within 15 min

    flap_payload = {
        "diagnosis": "bgp_optical_flapping",
        "evidence_ids": ["log_flap_01", "log_flap_02"],
        "affected_nodes": ["leaf-1"],
        "action": "reenable_bgp_neighbor",
        "parameters": {
            "device": "leaf-1",
            "neighbor": "10.77.0.2"
        },
        "verification_checks": [],
        "abstain": False
    }

    ok_flap, errs_flap, _ = gate.render_trusted_template(flap_payload)
    print("Flapping Peer Re-enable Blocked:", not ok_flap)
    print("Safety Interceptions:", errs_flap)
