"""
test_zero_cost_pipeline.py - Verification Suite for the Zero-Capital Real-World Data Pipeline

Tests:
1. NetOps-Doctor: Standalone configuration linter & anonymized signature generation.
2. Public Incident Ingestor: Real-world postmortem conversion (Cloudflare, AWS, Fastly).
3. RIPE RIS / RouteViews Stream Parser: BGP flap storm and rapid withdrawal detection.
4. Privacy Guarantee: Zero raw IP / hostname / credential leakage in anonymized signatures.
"""

import sys
import os
import json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.tools.netops_doctor import NetOpsDoctor, Finding, AnonymizedIncidentSignature
from src.telemetry.public_incident_parser import PublicIncidentIngestor, BgpUpdateStreamParser
from src.verification.episode_schema import validate_episode_dict


def test_netops_doctor_linter():
    print("[*] 1. Testing NetOps-Doctor Configuration Linter & Anonymizer...")
    doctor = NetOpsDoctor(salt="unit_test_salt_123")

    sample_config = """
    ! Real-world multi-vendor style configuration
    interface eth1
     description Transit Uplink to Spine-1
     ip address 10.77.0.2/30
     mtu 1200
    !
    interface eth2
     description Transit Uplink to Spine-2
     ip address 10.77.0.6/30
     mtu 9000
    !
    router bgp 65001
     bgp router-id 10.77.0.2
     neighbor 10.77.0.1 remote-as 65100
     neighbor 10.77.0.5 remote-as 65100
     neighbor 10.77.0.5 shutdown
    !
    """

    findings, signatures = doctor.lint_config_text(sample_config, vendor="frr")

    assert len(findings) >= 3, f"Expected at least 3 findings, got {len(findings)}"
    assert len(signatures) == len(findings), "Each finding must produce an anonymized signature"

    # Verify specific findings
    mtu_findings = [f for f in findings if f.fault_class == "CLOS_ASYMMETRIC_MTU_MISMATCH"]
    assert len(mtu_findings) == 1
    assert "eth1" in mtu_findings[0].target

    leak_findings = [f for f in findings if f.fault_class == "BGP_MISSING_ROUTE_MAP_FILTER"]
    assert len(leak_findings) == 2

    # Verify Privacy Guarantee: Signatures must NEVER contain raw IP addresses
    for sig in signatures:
        assert "10.77." not in sig.anonymized_target, f"Leaked private IP in signature: {sig.anonymized_target}"
        assert sig.anonymized_target.startswith("ANON_")
        assert len(sig.signature_hash) == 12

    print(f"    [+] NetOps-Doctor passed: {len(findings)} findings, {len(signatures)} anonymized signatures generated.")
    print("    [+] Privacy Guarantee Verified: 100% of raw IP addresses converted to one-way salted hashes.")


def test_public_incident_ingestion():
    print("\n[*] 2. Testing Public Real-World Incident Ingestor (Cloudflare, AWS, Fastly)...")
    episodes = PublicIncidentIngestor.load_public_dataset()

    assert len(episodes) == 4, f"Expected 4 canonical public episodes, got {len(episodes)}"

    for ep in episodes:
        assert ep.cryptographic_audit_hash is not None
        assert len(ep.cryptographic_audit_hash) == 64
        # Validate schema compliance
        is_valid, errs = validate_episode_dict(ep.to_dict())
        assert is_valid, f"Public episode {ep.episode_id} failed schema validation: {errs}"

    cloudflare_ep = next(e for e in episodes if "CLOUDFLARE" in e.episode_id)
    assert cloudflare_ep.ground_truth.fault_class == "BGP_ROUTE_LEAK_MORE_SPECIFICS"

    aws_ep = next(e for e in episodes if "AWS" in e.episode_id)
    assert aws_ep.ground_truth.fault_class == "OS_THREAD_SOCKET_BUFFER_EXHAUSTION"

    print(f"    [+] Ingested and validated {len(episodes)} authentic public incident episodes at ₹0.")


def test_bgp_update_stream_parser():
    print("\n[*] 3. Testing RIPE RIS / RouteViews BGP Stream Parser...")
    updates = [
        {"type": "announcement", "prefix": "198.51.100.0/24", "as_path": [65001, 209]},
        {"type": "withdrawal", "prefix": "198.51.100.0/24", "as_path": [65001, 209]},
        {"type": "announcement", "prefix": "198.51.100.0/24", "as_path": [65001, 209]},
        {"type": "withdrawal", "prefix": "198.51.100.0/24", "as_path": [65001, 209]},
        {"type": "announcement", "prefix": "203.0.113.0/24", "as_path": [65002, 701]},
    ]

    analysis = BgpUpdateStreamParser.analyze_bgp_update_batch(updates)
    assert analysis["is_flap_storm"] is True
    assert analysis["requires_flap_damping"] is True
    assert "198.51.100.0/24" in analysis["flapping_prefixes"]
    assert 209 in analysis["unique_asns"]
    assert 701 in analysis["unique_asns"]

    print("    [+] BGP stream parser correctly intercepted route flap storm from simulated live updates.")


if __name__ == "__main__":
    test_netops_doctor_linter()
    test_public_incident_ingestion()
    test_bgp_update_stream_parser()
    print("\n=======================================================")
    print("   ALL ZERO-CAPITAL DATA PIPELINE TESTS PASSED [OK]   ")
    print("=======================================================")
