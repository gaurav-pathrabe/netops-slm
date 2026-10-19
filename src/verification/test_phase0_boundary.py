"""
test_phase0_boundary.py - Validation Suite for Phase 0 Autonomous Boundary

Tests:
1. Fault Ontology v1 (15 classes, safety tiers, invariants, rollbacks)
2. Incident Episode Schema v1 & SHA-256 Cryptographic Audit Ledger
3. The Ten Mandatory Gate Checks in TypedActionGate
"""

import sys
import os
import json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.verification.fault_ontology import (
    FAULT_ONTOLOGY_V1,
    SafetyTier,
    get_fault_class,
    list_fault_classes,
    get_autonomous_fault_classes
)
from src.verification.episode_schema import (
    IncidentEpisode,
    GroundTruthFault,
    TelemetrySignature,
    DiagnosisTrace,
    GateEvaluationTrace,
    ExecutionTrace,
    validate_episode_dict
)
from src.verification.typed_action_gate import TypedActionGate, CLOS_INVENTORY


def test_fault_ontology():
    print("[*] 1. Testing Fault Ontology v1...")
    classes = list_fault_classes()
    assert len(classes) == 15, f"Expected 15 fault classes, got {len(classes)}"

    auto_classes = get_autonomous_fault_classes()
    print(f"    - Total Fault Classes: {len(classes)}")
    print(f"    - Autonomous Remediation Classes: {len(auto_classes)} ({auto_classes})")

    # Verify key invariants on specific classes
    flap_defn = get_fault_class("BGP_RAPID_ROUTE_FLAPPING")
    assert flap_defn is not None
    assert flap_defn.safety_tier == SafetyTier.FORBIDDEN_AUTOMATION
    assert flap_defn.typed_action == "none"

    mtu_defn = get_fault_class("CLOS_ASYMMETRIC_MTU_MISMATCH")
    assert mtu_defn is not None
    assert mtu_defn.safety_tier == SafetyTier.SAFE_AUTONOMOUS
    assert mtu_defn.typed_action == "isolate_degraded_path"
    assert mtu_defn.rollback_action == "restore_spine_path"

    control_defn = get_fault_class("BENIGN_TRANSIENT_SPIKE")
    assert control_defn is not None
    assert control_defn.safety_tier == SafetyTier.SAFE_AUTONOMOUS
    assert control_defn.typed_action == "none"

    print("    [+] Fault Ontology v1 Invariants Verified.")


def test_episode_schema_and_audit():
    print("\n[*] 2. Testing Episode Schema v1 & Cryptographic Audit Ledger...")
    ep = IncidentEpisode(
        episode_id="EP_PHASE0_001",
        topology_type="4-node-spine-leaf-clos",
        vendor_nos=["frr"],
        ground_truth=GroundTruthFault(
            fault_class="CLOS_ASYMMETRIC_MTU_MISMATCH",
            category="FABRIC_PHYSICAL",
            affected_devices=["leaf-1", "spine-1"],
            affected_interfaces=["eth1"],
            injected_state={"mtu": 1200},
            target_action="isolate_degraded_path",
            target_rollback="restore_spine_path"
        ),
        telemetry=TelemetrySignature(
            loss_rate_small=0.0,
            loss_rate_jumbo=100.0,
            bgp_established_count=4,
            bgp_down_count=0,
            active_ecmp_paths=2,
            crc_error_delta=0,
            syslog_patterns=["MTU path discovery drop"],
            raw_evidence_ids=["ping_jumbo_fail_01", "mtu_probe_02"]
        ),
        diagnosis=DiagnosisTrace(
            agent_id="netops-react-agent",
            model_version="v3-hybrid",
            observations=["Small pings 0% loss, jumbo pings 100% loss via spine-1 uplink eth1"],
            tool_calls=[{"tool": "check_canary_loss", "status": "FAIL"}],
            ranked_differential=[{"hypothesis": "CLOS_ASYMMETRIC_MTU_MISMATCH", "confidence": 0.96}],
            proposed_action="isolate_degraded_path",
            parameters={"device": "leaf-1", "interface": "eth1"},
            abstain=False
        ),
        gate_evaluation=GateEvaluationTrace(
            check_1_schema_valid=True,
            check_2_policy_allowed=True,
            check_3_live_preconditions=True,
            check_4_verifier_proof=True,
            check_5_blast_radius_bounded=True,
            check_6_approval_level="AUTO_APPROVED",
            check_7_change_window_valid=True,
            check_8_rollback_defined=True,
            check_9_idempotency_verified=True,
            check_10_audit_logged=True,
            all_checks_passed=True
        ),
        execution=ExecutionTrace(
            action_executed="isolate_degraded_path",
            rendered_command="docker exec clab-netops-spine-leaf-lab-leaf-1 ip link set dev eth1 down",
            execution_status="CONFIRMED",
            postcondition_verified=True,
            rollback_command="docker exec clab-netops-spine-leaf-lab-leaf-1 ip link set dev eth1 up",
            rollback_status="READY",
            execution_latency_ms=1.42
        )
    )

    ep.finalize()
    assert ep.cryptographic_audit_hash, "Audit hash must not be empty"
    print(f"    - Cryptographic Audit Hash: {ep.cryptographic_audit_hash}")

    is_valid, errs = validate_episode_dict(ep.to_dict())
    assert is_valid, f"Episode validation errors: {errs}"
    print("    [+] Episode Schema & Audit Hash Passed.")


def test_ten_gate_checks():
    print("\n[*] 3. Testing The Ten Mandatory Gate Checks in TypedActionGate...")
    gate = TypedActionGate(inventory=CLOS_INVENTORY, enable_digital_twin=True)

    # Test A: Safe autonomous action with active live telemetry
    payload_a = {
        "diagnosis": "CLOS_ASYMMETRIC_MTU_MISMATCH",
        "evidence_ids": ["ping_jumbo_drop_01"],
        "affected_nodes": ["leaf-1"],
        "action": "isolate_degraded_path",
        "parameters": {"device": "leaf-1", "interface": "eth1"},
        "verification_checks": ["zero_loss_post_failover"],
        "abstain": False
    }
    telemetry_a = {"packet_loss": 100.0, "crc_errors": 0}
    res_a = gate.evaluate_ten_checks(payload_a, initial_telemetry=telemetry_a, incident_id="INC_TEST_A")
    assert res_a["all_passed"] is True, f"Expected all passed, got rejections: {res_a['rejections']}"
    assert res_a["check_8_rollback_defined"] is True
    assert "ip link set dev eth1 up" in res_a["rollback_command"]
    print("    [+] Test A (Safe Autonomous Action): All 10 Checks Passed.")

    # Test B: Live Precondition Failure (trying to isolate path with zero packet loss)
    telemetry_b = {"packet_loss": 0.0, "crc_errors": 0}
    res_b = gate.evaluate_ten_checks(payload_a, initial_telemetry=telemetry_b, incident_id="INC_TEST_B")
    assert res_b["all_passed"] is False
    assert res_b["check_3_live_preconditions"] is False
    print("    [+] Test B (Precondition Failure): Correctly Intercepted.")

    # Test C: Blast Radius Exceeded (4 nodes affected when limit is 2)
    payload_c = {**payload_a, "affected_nodes": ["leaf-1", "spine-1", "leaf-2", "spine-2"]}
    res_c = gate.evaluate_ten_checks(payload_c, policy_context={"max_affected_nodes": 2}, incident_id="INC_TEST_C")
    assert res_c["all_passed"] is False
    assert res_c["check_5_blast_radius_bounded"] is False
    print("    [+] Test C (Blast Radius Exceeded): Correctly Intercepted.")

    # Test D: Shell Injection Attempt
    payload_d = {
        **payload_a,
        "parameters": {"device": "leaf-1; rm -rf /", "interface": "eth1"}
    }
    res_d = gate.evaluate_ten_checks(payload_d, incident_id="INC_TEST_D")
    assert res_d["all_passed"] is False
    assert res_d["check_1_schema_valid"] is False
    print("    [+] Test D (Shell Injection Attempt): Correctly Intercepted.")

    # Test E: Action Requiring Human Supervisor Authorization (e.g. drain_spine_traffic)
    payload_e = {
        "diagnosis": "CLOS_ECMP_ROUTE_BLACKHOLE",
        "evidence_ids": ["rib_discrepancy_01"],
        "affected_nodes": ["spine-1"],
        "action": "drain_spine_traffic",
        "parameters": {"device": "spine-1", "neighbor": "10.77.0.1"},
        "verification_checks": ["ecmp_rebalance"],
        "abstain": False
    }
    # E1: Without approval -> Blocked
    res_e1 = gate.evaluate_ten_checks(payload_e, incident_id="INC_TEST_E1")
    assert res_e1["all_passed"] is False
    assert res_e1["check_6_approval_level"] == "REQUIRES_HUMAN"
    print("    [+] Test E1 (Supervised Action Without Approval): Blocked as REQUIRES_HUMAN.")

    # E2: With human approval -> Passed
    res_e2 = gate.evaluate_ten_checks(payload_e, approval_context={"approved_by": "sec_operator_42"}, incident_id="INC_TEST_E2")
    assert res_e2["all_passed"] is True
    assert res_e2["check_6_approval_level"] == "HUMAN_APPROVED"
    assert "route-map RM_DRAIN" in res_e2["execution_command"]
    print("    [+] Test E2 (Supervised Action With Human Approval): Passed as HUMAN_APPROVED.")


if __name__ == "__main__":
    test_fault_ontology()
    test_episode_schema_and_audit()
    test_ten_gate_checks()
    print("\n=======================================================")
    print("   ALL PHASE 0 AUTONOMOUS BOUNDARY INVARIANTS PASSED   ")
    print("=======================================================")
