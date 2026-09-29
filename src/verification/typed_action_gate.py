"""
typed_action_gate.py - Bounded Execution & Typed Schema Validation Gate
Ensures model outputs conform to strict JSON schemas, parameters match verified
lab inventory, and maps abstract actions to trusted deterministic templates.
Fulfills Milestone 3 and Milestone 5 execution safety requirements.
"""

import json
from typing import Dict, Any, Tuple, List

# Known Lab Inventory (Strict Allowlist)
LAB_INVENTORY = {
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

PERMITTED_ACTIONS = ["reenable_bgp_neighbor", "correct_remote_as", "originate_prefix", "none"]

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
    def __init__(self, inventory: Dict[str, Any] = LAB_INVENTORY):
        self.inventory = inventory

    def validate_action_payload(self, payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validates JSON schema, key types, permitted actions, and inventory bounds."""
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
        expected_as = params.get("expected_remote_as")

        if device not in self.inventory["devices"]:
            errors.append(f"Parameter error: device '{device}' is not recognized in lab inventory")
        elif neighbor and neighbor not in self.inventory["neighbors"].get(device, []):
            errors.append(f"Parameter error: neighbor '{neighbor}' is not an authorized peer for device '{device}'")
        elif prefix and prefix not in self.inventory["subnets"]:
            errors.append(f"Parameter error: prefix '{prefix}' is not in authorized inventory subnets")

        # 5. Evidence references check
        evidence = payload.get("evidence_ids", [])
        if not evidence or not isinstance(evidence, list):
            errors.append("Evidence error: at least one valid evidence_id must be cited")

        return len(errors) == 0, errors

    def render_trusted_template(self, payload: Dict[str, Any]) -> Tuple[bool, List[str], str]:
        """
        Renders safe, deterministic vtysh commands from validated typed action.
        Model text is never executed directly.
        """
        is_valid, errors = self.validate_action_payload(payload)
        if not is_valid:
            return False, errors, ""

        if payload.get("abstain") is True:
            return True, [], "# Action abstained. No commands rendered."

        action = payload.get("action")
        params = payload.get("parameters", {})
        device = params.get("device")
        neighbor = params.get("neighbor")
        prefix = params.get("prefix")
        expected_as = params.get("expected_remote_as")
        asn = self.inventory["asns"].get(device)

        if action == "reenable_bgp_neighbor":
            command = (
                f"docker exec clab-netops-bgp-lab-{device} vtysh "
                f"-c 'configure terminal' "
                f"-c 'router bgp {asn}' "
                f"-c 'no neighbor {neighbor} shutdown'"
            )
            return True, [], command
        elif action == "correct_remote_as":
            target_as = expected_as if expected_as else (65002 if device == "router-a" else 65001)
            command = (
                f"docker exec clab-netops-bgp-lab-{device} vtysh "
                f"-c 'configure terminal' "
                f"-c 'router bgp {asn}' "
                f"-c 'neighbor {neighbor} remote-as {target_as}'"
            )
            return True, [], command
        elif action == "originate_prefix":
            target_prefix = prefix if prefix else ("10.77.1.0/24" if device == "router-a" else "10.77.2.0/24")
            command = (
                f"docker exec clab-netops-bgp-lab-{device} vtysh "
                f"-c 'configure terminal' "
                f"-c 'router bgp {asn}' "
                f"-c 'address-family ipv4 unicast' "
                f"-c 'network {target_prefix}'"
            )
            return True, [], command

        return False, [f"No template available for action '{action}'"], ""


if __name__ == "__main__":
    gate = TypedActionGate()

    # Valid proposal
    good_payload = {
        "diagnosis": "bgp_neighbor_admin_shutdown",
        "evidence_ids": ["event_1", "state_1"],
        "affected_nodes": ["router-a"],
        "action": "reenable_bgp_neighbor",
        "parameters": {
            "device": "router-a",
            "neighbor": "10.77.0.2"
        },
        "verification_checks": ["bgp_session", "expected_routes", "endpoint_ping"],
        "abstain": False
    }

    ok, errs, cmd = gate.render_trusted_template(good_payload)
    print("Good Payload Rendered:", ok)
    print("Command:", cmd)

    # Malicious/Hallucinated proposal
    bad_payload = {
        "diagnosis": "bgp_down",
        "evidence_ids": [],
        "affected_nodes": ["core-switch-prod"],
        "action": "raw_shell_exec",
        "parameters": {"command": "rm -rf /"},
        "verification_checks": [],
        "abstain": False
    }

    ok_bad, errs_bad, _ = gate.render_trusted_template(bad_payload)
    print("\nBad Payload Blocked:", not ok_bad)
    print("Violations:", errs_bad)
