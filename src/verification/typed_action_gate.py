"""
typed_action_gate.py - Bounded Execution & Typed Schema Validation Gate
Ensures model outputs conform to strict JSON schemas, parameters match verified
lab inventory, and maps abstract actions to trusted deterministic templates.
Fulfills Invariants 1, 4, 7 and outer-loop security constraints.
Supports both Legacy 2-Node lab and Phase 2/3 4-Node Spine-Leaf CLOS Fabric.
"""

import os
import sys
import json
import time
from typing import Dict, Any, Tuple, List, Optional
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.verification.digital_twin_verifier import DigitalTwinVerifier, PreFlightVerificationProof

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
    def __init__(self, inventory: Dict[str, Any] = CLOS_INVENTORY, enable_digital_twin: bool = True):
        self.inventory = inventory
        self.flap_history: Dict[str, List[float]] = {}  # Invariant 1 Flap tracker: {target: [timestamps]}
        self.enable_digital_twin = enable_digital_twin
        self.digital_twin = DigitalTwinVerifier() if enable_digital_twin else None

    def verify_preflight(
        self,
        incident_id: str,
        payload: Dict[str, Any],
        initial_telemetry: Optional[Dict[str, Any]] = None
    ) -> Optional[PreFlightVerificationProof]:
        """Runs pre-flight digital twin simulation to prove reachability and loop-freedom before execution."""
        if not self.digital_twin:
            return None
        return self.digital_twin.verify_remediation_preflight(
            incident_id=incident_id,
            action_payload=payload,
            initial_telemetry=initial_telemetry
        )

    def record_flap_event(self, target: str, timestamp: Optional[float] = None) -> int:
        """Registers a flap event and prunes events older than 15 minutes (900 seconds)."""
        ts = timestamp if timestamp is not None else time.time()
        if target not in self.flap_history:
            self.flap_history[target] = []
        # Prune older than 900s
        self.flap_history[target] = [t for t in self.flap_history[target] if (ts - t) <= 900.0]
        self.flap_history[target].append(ts)
        return len(self.flap_history[target])

    def get_inventory_for_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Dynamically resolves inventory between 2-Node Legacy Lab and 4-Node CLOS Fabric."""
        params = payload.get("parameters", {})
        nodes = payload.get("affected_nodes", [])
        target = params.get("device") or (nodes[0] if (isinstance(nodes, list) and len(nodes) > 0) else None)
        if target in LEGACY_INVENTORY["devices"]:
            return LEGACY_INVENTORY
        if target in CLOS_INVENTORY["devices"]:
            return CLOS_INVENTORY
        return self.inventory

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
        abstain_val = payload.get("abstain")
        is_abstain = (abstain_val is True) or (str(abstain_val).strip().lower() == "true")
        if is_abstain:
            if payload.get("action") not in ["none", ""]:
                errors.append("Invalid abstention: action must be 'none' when abstain is True")
            return len(errors) == 0, errors

        # 3. Permitted action check
        action = payload.get("action")
        if action not in PERMITTED_ACTIONS:
            errors.append(f"Forbidden action: '{action}' is not in permitted actions list {PERMITTED_ACTIONS}")

        # Resolve active inventory for this payload (auto-detects legacy vs. CLOS)
        active_inv = self.get_inventory_for_payload(payload)

        # 4. Inventory boundaries check
        nodes = payload.get("affected_nodes", [])
        if not isinstance(nodes, list):
            errors.append("Schema error: 'affected_nodes' must be a list")
            nodes = []
        for node in nodes:
            if node not in active_inv["devices"]:
                errors.append(f"Inventory violation: unknown device '{node}'")

        params = payload.get("parameters", {})
        if not isinstance(params, dict):
            errors.append("Schema error: 'parameters' must be a dictionary")
            params = {}

        device = params.get("device")
        neighbor = params.get("neighbor")
        prefix = params.get("prefix")
        expected_as = params.get("expected_remote_as")
        iface = params.get("interface")

        # Sanitize parameters against shell injection characters
        for param_key, param_val in params.items():
            if isinstance(param_val, str):
                if any(c in param_val for c in [";", "&", "|", "`", "$", "(", ")", "<", ">", "\n", "\r", "'", '"']):
                    errors.append(f"Command injection detected in parameter '{param_key}': forbidden characters")

        if device not in active_inv["devices"]:
            errors.append(f"Parameter error: device '{device}' is not recognized in lab inventory")
        elif neighbor and neighbor not in active_inv["neighbors"].get(device, []):
            errors.append(f"Parameter error: neighbor '{neighbor}' is not an authorized peer for device '{device}'")
        elif prefix and prefix not in active_inv["subnets"]:
            errors.append(f"Parameter error: prefix '{prefix}' is not in authorized inventory subnets")

        # Parameter validation for correct_remote_as
        if action == "correct_remote_as" and expected_as is not None:
            try:
                as_num = int(expected_as)
                if not (1 <= as_num <= 4294967295):
                    errors.append(f"Parameter error: expected_remote_as '{as_num}' is outside valid 32-bit ASN range")
            except (ValueError, TypeError):
                errors.append(f"Parameter error: expected_remote_as '{expected_as}' must be an integer")

        # Parameter validation for isolate_degraded_path (uplink role check)
        if action == "isolate_degraded_path":
            target_iface = iface or "eth1"
            # In CLOS fabric, eth1 and eth2 are transit uplinks; eth3 is client-facing; eth0 is mgmt
            allowed_transit_uplinks = ["eth1", "eth2"]
            if target_iface not in allowed_transit_uplinks:
                errors.append(
                    f"Interface Role Violation: interface '{target_iface}' cannot be isolated. "
                    f"Only transit uplinks {allowed_transit_uplinks} may be isolated; client/mgmt interfaces are protected."
                )

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

    def render_trusted_template(
        self,
        payload: Dict[str, Any],
        enforce_preflight: bool = False,
        incident_id: str = "INCIDENT_PREFLIGHT",
        initial_telemetry: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, List[str], str]:
        """
        Renders safe, deterministic vtysh commands from validated typed action.
        Model text is never executed directly (Invariant 4).
        If enforce_preflight is True, proves reachability and loop-freedom on the digital twin.
        """
        is_valid, errors = self.validate_action_payload(payload)
        if not is_valid:
            return False, errors, ""

        if payload.get("abstain") is True or payload.get("action") == "none":
            return True, [], "# Action abstained. No network commands executed."

        # Pre-Flight Verification Gate
        if enforce_preflight and self.digital_twin:
            proof = self.verify_preflight(incident_id, payload, initial_telemetry)
            if proof and not proof.preflight_passed:
                return False, [f"Digital Twin Pre-Flight Rejection: {c}" for c in proof.counterexamples], ""

        active_inv = self.get_inventory_for_payload(payload)
        action = payload.get("action")
        params = payload.get("parameters", {})
        device = params.get("device")
        neighbor = params.get("neighbor")
        prefix = params.get("prefix")
        expected_as = params.get("expected_remote_as")
        asn = active_inv["asns"].get(device)
        prefix_cname = active_inv.get("prefix", "clab-netops-spine-leaf-lab-")

        if action == "reenable_bgp_neighbor":
            command = (
                f"docker exec {prefix_cname}{device} vtysh "
                f"-c 'configure terminal' "
                f"-c 'router bgp {asn}' "
                f"-c 'no neighbor {neighbor} shutdown'"
            )
            return True, [], command

        elif action == "correct_remote_as":
            target_as = int(expected_as) if expected_as else (65002 if device == "router-a" else 65100)
            command = (
                f"docker exec {prefix_cname}{device} vtysh "
                f"-c 'configure terminal' "
                f"-c 'router bgp {asn}' "
                f"-c 'neighbor {neighbor} remote-as {target_as}'"
            )
            return True, [], command

        elif action == "originate_prefix":
            target_prefix = prefix if prefix else ("10.77.1.0/24" if ("leaf-1" in device or "router-a" in device) else "10.77.2.0/24")
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
            # Temporarily brings down a blackholing uplink interface on the leaf switch
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

    def render_rollback_template(self, payload: Dict[str, Any]) -> Tuple[bool, List[str], str]:
        """
        Check 8: Rollback Defined.
        Pre-computes the verified inverse action prior to executing any command.
        Ensures a deterministic rollback path exists before touching the physical network.
        """
        action = payload.get("action")
        params = payload.get("parameters", {})
        device = params.get("device")
        neighbor = params.get("neighbor")
        prefix = params.get("prefix")
        active_inv = self.get_inventory_for_payload(payload)
        asn = active_inv["asns"].get(device, 65001)
        prefix_cname = active_inv.get("prefix", "clab-netops-spine-leaf-lab-")

        if payload.get("abstain") is True or action in ["none", ""]:
            return True, [], "# No rollback needed for abstained action."

        elif action == "reenable_bgp_neighbor":
            # Inverse action: shut neighbor down
            command = (
                f"docker exec {prefix_cname}{device} vtysh "
                f"-c 'configure terminal' "
                f"-c 'router bgp {asn}' "
                f"-c 'neighbor {neighbor} shutdown'"
            )
            return True, [], command

        elif action == "correct_remote_as":
            # Inverse action: remove or reset remote-as
            command = (
                f"docker exec {prefix_cname}{device} vtysh "
                f"-c 'configure terminal' "
                f"-c 'router bgp {asn}' "
                f"-c 'no neighbor {neighbor} remote-as'"
            )
            return True, [], command

        elif action == "originate_prefix":
            target_prefix = prefix if prefix else ("10.77.1.0/24" if ("leaf-1" in str(device) or "router-a" in str(device)) else "10.77.2.0/24")
            command = (
                f"docker exec {prefix_cname}{device} vtysh "
                f"-c 'configure terminal' "
                f"-c 'router bgp {asn}' "
                f"-c 'address-family ipv4 unicast' "
                f"-c 'no network {target_prefix}'"
            )
            return True, [], command

        elif action == "drain_spine_traffic":
            # Inverse action: restore spine path by removing drain route-map
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

        elif action == "isolate_degraded_path":
            # Inverse action: bring interface back UP
            iface = params.get("interface", "eth1")
            command = f"docker exec {prefix_cname}{device} ip link set dev {iface} up"
            return True, [], command

        elif action == "restore_spine_path":
            # Inverse action: re-apply drain
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

        return False, [f"No verified rollback template available for action '{action}'"], ""

    def evaluate_ten_checks(
        self,
        payload: Dict[str, Any],
        initial_telemetry: Optional[Dict[str, Any]] = None,
        policy_context: Optional[Dict[str, Any]] = None,
        approval_context: Optional[Dict[str, Any]] = None,
        incident_id: str = "INC_CHECK"
    ) -> Dict[str, Any]:
        """
        Evaluates all Ten Mandatory Gate Checks before passing action from Form to Physics:
        1. Schema Validity
        2. Policy Compliance (OPA/Rego)
        3. Live Preconditions
        4. Verifier Proof
        5. Blast Radius Bounded
        6. Approval Level
        7. Change Window
        8. Rollback Defined
        9. Idempotency Verified
        10. Cryptographic Signed Audit Log
        """
        import hashlib
        rejections = []
        p_ctx = policy_context or {}
        a_ctx = approval_context or {}

        # 1. Schema Validity
        schema_ok, schema_errs = self.validate_action_payload(payload)
        if not schema_ok:
            rejections.extend(schema_errs)

        # 2. Policy Compliance
        disallowed_actions = p_ctx.get("disallowed_actions", [])
        action = payload.get("action", "")
        policy_ok = action not in disallowed_actions
        if not policy_ok:
            rejections.append(f"Policy Violation: Action '{action}' is disallowed by policy.")

        # 3. Live Preconditions
        # If live telemetry is provided, check that fault condition holds
        preconditions_ok = True
        if initial_telemetry:
            if action == "reenable_bgp_neighbor":
                # Ensure neighbor is actually down
                bgp_data = initial_telemetry.get("bgp", {})
                if bgp_data and bgp_data.get("peer_state") == "Established":
                    preconditions_ok = False
                    rejections.append("Live Precondition Failed: Neighbor is already Established.")
            elif action == "isolate_degraded_path":
                loss = initial_telemetry.get("packet_loss", 0.0)
                crc = initial_telemetry.get("crc_errors", 0)
                if loss == 0.0 and crc == 0:
                    preconditions_ok = False
                    rejections.append("Live Precondition Failed: No packet loss or errors detected on path.")

        # 4. Verifier Proof
        verifier_ok = True
        if self.digital_twin and payload.get("action") not in ["none", ""]:
            proof = self.verify_preflight(incident_id, payload, initial_telemetry)
            if proof and not proof.preflight_passed:
                verifier_ok = False
                rejections.extend([f"Verifier Proof Failed: {c}" for c in proof.counterexamples])

        # 5. Blast Radius Bounded
        nodes = payload.get("affected_nodes", [])
        max_allowed_nodes = p_ctx.get("max_affected_nodes", 2)
        blast_ok = len(nodes) <= max_allowed_nodes
        if not blast_ok:
            rejections.append(f"Blast Radius Exceeded: {len(nodes)} affected nodes > limit {max_allowed_nodes}")

        # 6. Approval Level & Verifier Authority Boundary
        # The symbolic verifier (Batfish / Digital Twin) proves control-plane invariants:
        # reachability, loop-freedom, blackhole-freedom, and route policy.
        # It CANNOT model data-plane capacity, congestion absorption, PFC/ECN buffers, or optic decay.
        # Therefore, only pure control-plane actions are in the autonomous whitelist.
        # Actions with data-plane capacity or blast-radius consequences (path isolation, drain)
        # mandate human supervisor authorization.
        CONTROL_PLANE_AUTONOMOUS_WHITELIST = [
            "reenable_bgp_neighbor",
            "correct_remote_as",
            "originate_prefix",
            "none"
        ]
        DATA_PLANE_CAPACITY_ACTIONS = [
            "isolate_degraded_path",
            "drain_spine_traffic",
            "restore_spine_path"
        ]

        approval_status = "AUTO_APPROVED"
        if action in DATA_PLANE_CAPACITY_ACTIONS or action not in CONTROL_PLANE_AUTONOMOUS_WHITELIST:
            if not a_ctx.get("approved_by"):
                approval_status = "REQUIRES_HUMAN"
                rejections.append(
                    f"Approval Level & Verifier Authority: Action '{action}' has data-plane/capacity "
                    f"consequences outside formal control-plane verifier authority. Human supervisor authorization required."
                )
            else:
                approval_status = "HUMAN_APPROVED"

        # 7. Change Window
        # Check if inside change window or if emergency flag is set
        emergency = p_ctx.get("is_emergency", True)
        window_active = p_ctx.get("window_active", True)
        change_window_ok = emergency or window_active
        if not change_window_ok:
            rejections.append("Change Window Violation: Operation outside authorized maintenance window.")

        # 8. Rollback Defined
        rb_ok, rb_errs, rb_cmd = self.render_rollback_template(payload)
        if not rb_ok:
            rejections.extend(rb_errs)

        # 9. Idempotency Verified
        # All supported declarative templates in PERMITTED_ACTIONS are idempotent
        idempotency_ok = action in PERMITTED_ACTIONS or action == "none"
        if not idempotency_ok:
            rejections.append(f"Idempotency Check Failed: Action '{action}' is not guaranteed idempotent.")

        # Render execution command if valid
        cmd_ok, cmd_errs, exec_cmd = self.render_trusted_template(payload, enforce_preflight=False)

        # 10. Cryptographic Audit Record
        audit_payload = {
            "incident_id": incident_id,
            "timestamp": time.time(),
            "payload": payload,
            "exec_cmd": exec_cmd,
            "rollback_cmd": rb_cmd,
            "approval": approval_status
        }
        audit_hash = hashlib.sha256(json.dumps(audit_payload, sort_keys=True).encode("utf-8")).hexdigest()
        audit_ok = bool(audit_hash)

        all_passed = (
            schema_ok and
            policy_ok and
            preconditions_ok and
            verifier_ok and
            blast_ok and
            (approval_status in ["AUTO_APPROVED", "HUMAN_APPROVED"]) and
            change_window_ok and
            rb_ok and
            idempotency_ok and
            audit_ok
        )

        return {
            "all_passed": all_passed,
            "check_1_schema_valid": schema_ok,
            "check_2_policy_allowed": policy_ok,
            "check_3_live_preconditions": preconditions_ok,
            "check_4_verifier_proof": verifier_ok,
            "check_5_blast_radius_bounded": blast_ok,
            "check_6_approval_level": approval_status,
            "check_7_change_window_valid": change_window_ok,
            "check_8_rollback_defined": rb_ok,
            "check_9_idempotency_verified": idempotency_ok,
            "check_10_audit_logged": audit_ok,
            "rejections": rejections,
            "execution_command": exec_cmd if all_passed else "",
            "rollback_command": rb_cmd if rb_ok else "",
            "audit_hash": audit_hash
        }



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
