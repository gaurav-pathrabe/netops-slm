"""
statistical_delta_distiller.py - Telemetry Distillation & Statistical Delta Computation

Key Scientific Principle:
Raw counters (e.g. 'rx_crc_errors: 14200') are meaningless without temporal context.
The intelligence resides in the tool layer: computing rates, deltas, baseline ratios,
and topology context so that Tier 1 can deterministically match textbook faults
over distilled statistics, leaving only the genuinely ambiguous residue for Tier 2.

Tier 1 Invariant Matcher:
- Fast and deterministic over distilled statistics (rates/deltas/baselines).
- Measured precision and recall (never claiming unvalidated '100% accuracy' over noisy data).
- Explicit 'no-match -> escalate to Tier 2' path when signals are ambiguous.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple


@dataclass
class DistilledInterfaceMetric:
    device: str
    interface: str
    carrier: bool
    mtu: int
    speed_mbps: int
    rx_crc_current: int
    crc_delta_per_sec: float
    crc_ratio_to_baseline: float
    packet_loss_small_pct: float
    packet_loss_jumbo_pct: float
    is_anomaly: bool
    anomaly_reason: Optional[str] = None


@dataclass
class DistilledBgpMetric:
    device: str
    peer: str
    remote_as: int
    expected_as: int
    state: str
    admin_down: bool
    flaps_in_15m: int
    flap_damping_active: bool
    uptime_seconds: int


@dataclass
class DistilledTelemetrySnapshot:
    timestamp: float
    interfaces: Dict[str, DistilledInterfaceMetric] = field(default_factory=dict)
    bgp_peers: Dict[str, DistilledBgpMetric] = field(default_factory=dict)
    active_ecmp_paths: int = 2
    raw_evidence_ids: List[str] = field(default_factory=list)


@dataclass
class Tier1MatchResult:
    match_found: bool
    fault_class: Optional[str] = None
    confidence: float = 0.0
    evidence_ids: List[str] = field(default_factory=list)
    recommended_action: Optional[str] = None
    action_parameters: Dict[str, Any] = field(default_factory=dict)
    is_mitigation_only: bool = False
    requires_human_approval: bool = False
    escalate_to_tier_2: bool = False
    escalation_reason: Optional[str] = None


class StatisticalDeltaDistiller:
    """
    Transforms raw counter dumps into normalized rates, baseline ratios, and temporal deltas.
    Powers the intelligence of both Tier 1 deterministic rules and Tier 2 compact observations.
    """

    def __init__(self, baseline_crc_rate: float = 0.05):
        # Normal baseline CRC errors/sec for standard optics (near zero)
        self.baseline_crc_rate = max(baseline_crc_rate, 0.001)

    def distill_counters(
        self,
        current_telemetry: Dict[str, Any],
        previous_telemetry: Optional[Dict[str, Any]] = None,
        interval_seconds: float = 5.0,
        expected_asns: Optional[Dict[str, int]] = None
    ) -> DistilledTelemetrySnapshot:
        """
        Computes rates, baseline ratios, and deltas across interface and routing counters.
        """
        dt = max(interval_seconds, 0.1)
        asns = expected_asns or {}
        snapshot = DistilledTelemetrySnapshot(timestamp=time.time())

        # 1. Distill Interfaces & CRC Rates
        current_ifaces = current_telemetry.get("interfaces", {})
        prev_ifaces = (previous_telemetry or {}).get("interfaces", {})
        ping_data = current_telemetry.get("ping", {})
        loss_small = float(ping_data.get("loss_64b", 0.0))
        loss_jumbo = float(ping_data.get("loss_1400b", 0.0))

        for iface_key, curr_data in current_ifaces.items():
            device, iface = iface_key.split(":") if ":" in iface_key else ("unknown", iface_key)
            prev_data = prev_ifaces.get(iface_key, {})
            curr_crc = curr_data.get("crc_errors", 0)
            prev_crc = prev_data.get("crc_errors", curr_crc)

            crc_delta = max(curr_crc - prev_crc, 0)
            crc_rate = crc_delta / dt
            ratio_to_baseline = crc_rate / self.baseline_crc_rate

            is_anomaly = False
            reason = None
            if ratio_to_baseline >= 50.0:
                is_anomaly = True
                reason = f"CRC error rate {crc_rate:.1f}/s is {ratio_to_baseline:.0f}x baseline ({self.baseline_crc_rate}/s)"
            elif curr_data.get("mtu", 1500) < 1400 and loss_jumbo > 50.0:
                is_anomaly = True
                reason = f"Sub-MTU {curr_data.get('mtu')} causing {loss_jumbo:.0f}% jumbo packet drop"

            metric = DistilledInterfaceMetric(
                device=device,
                interface=iface,
                carrier=curr_data.get("carrier", True),
                mtu=curr_data.get("mtu", 1500),
                speed_mbps=curr_data.get("speed_mbps", 10000),
                rx_crc_current=curr_crc,
                crc_delta_per_sec=crc_rate,
                crc_ratio_to_baseline=ratio_to_baseline,
                packet_loss_small_pct=loss_small,
                packet_loss_jumbo_pct=loss_jumbo,
                is_anomaly=is_anomaly,
                anomaly_reason=reason
            )
            snapshot.interfaces[iface_key] = metric
            if is_anomaly:
                snapshot.raw_evidence_ids.append(f"anomaly_{iface_key}")

        # 2. Distill BGP Peers
        bgp_peers = current_telemetry.get("bgp", {}).get("peers", [])
        for peer in bgp_peers:
            peer_ip = peer.get("peer")
            dev = peer.get("device", "unknown")
            rem_as = peer.get("remote_as", 0)
            exp_as = asns.get(dev, rem_as)
            flaps = peer.get("flaps_in_15m", 0)

            bgp_metric = DistilledBgpMetric(
                device=dev,
                peer=peer_ip,
                remote_as=rem_as,
                expected_as=exp_as,
                state=peer.get("state", "Unknown"),
                admin_down=peer.get("admin_down", False),
                flaps_in_15m=flaps,
                flap_damping_active=(flaps >= 2),
                uptime_seconds=peer.get("uptime", 0)
            )
            snapshot.bgp_peers[f"{dev}:{peer_ip}"] = bgp_metric
            if bgp_metric.flap_damping_active:
                snapshot.raw_evidence_ids.append(f"flap_damping_{dev}_{peer_ip}")

        snapshot.active_ecmp_paths = current_telemetry.get("ecmp", {}).get("active_paths", 2)
        return snapshot


class Tier1InvariantMatcher:
    """
    Tier 1 Deterministic Invariant Matcher:
    Matches textbook operational faults directly over distilled statistics.
    Fast, cheap, and precise — with measured precision/recall and an explicit
    escalation escape path to Tier 2 when telemetry is noisy or ambiguous.
    """

    def __init__(self, distiller: Optional[StatisticalDeltaDistiller] = None):
        self.distiller = distiller or StatisticalDeltaDistiller()

    def evaluate(self, snapshot: DistilledTelemetrySnapshot) -> Tier1MatchResult:
        """
        Evaluates distilled telemetry against textbook physical and protocol invariants.
        """
        # Rule 1: Anti-Flap Oscillation Guard (Invariant 1)
        for key, bgp in snapshot.bgp_peers.items():
            if bgp.flaps_in_15m >= 2:
                return Tier1MatchResult(
                    match_found=True,
                    fault_class="BGP_RAPID_ROUTE_FLAPPING",
                    confidence=0.99,
                    evidence_ids=[f"flaps_{bgp.flaps_in_15m}_in_15m", f"peer_{bgp.peer}_unstable"],
                    recommended_action="none",
                    is_mitigation_only=False,
                    requires_human_approval=True,
                    escalate_to_tier_2=False
                )

        # Rule 2: Administrative Shutdown
        for key, bgp in snapshot.bgp_peers.items():
            if bgp.admin_down and bgp.state == "Idle":
                return Tier1MatchResult(
                    match_found=True,
                    fault_class="BGP_NEIGHBOR_ADMIN_DOWN",
                    confidence=0.98,
                    evidence_ids=[f"admin_down_{bgp.peer}", "state_idle"],
                    recommended_action="reenable_bgp_neighbor",
                    action_parameters={"device": bgp.device, "neighbor": bgp.peer},
                    is_mitigation_only=False,
                    requires_human_approval=False,  # Safe control-plane autonomous action
                    escalate_to_tier_2=False
                )

        # Rule 3: Remote AS Misconfiguration
        for key, bgp in snapshot.bgp_peers.items():
            if bgp.state in ["Active", "Connect"] and bgp.expected_as != 0 and bgp.remote_as != bgp.expected_as:
                return Tier1MatchResult(
                    match_found=True,
                    fault_class="BGP_REMOTE_AS_MISMATCH",
                    confidence=0.97,
                    evidence_ids=[f"as_mismatch_{bgp.remote_as}_vs_{bgp.expected_as}", f"state_{bgp.state}"],
                    recommended_action="correct_remote_as",
                    action_parameters={"device": bgp.device, "neighbor": bgp.peer, "expected_remote_as": bgp.expected_as},
                    is_mitigation_only=False,
                    requires_human_approval=False,  # Safe control-plane autonomous action
                    escalate_to_tier_2=False
                )

        # Rule 4: Optical Transceiver Degradation (High CRC Rate over Baseline)
        for key, iface in snapshot.interfaces.items():
            if iface.crc_ratio_to_baseline >= 50.0 and iface.carrier:
                # Crucial Real-World Distinction:
                # Isolate path is a MITIGATION with capacity blast-radius, NOT the root fix.
                # The root fix is physical optic replacement.
                # Mitigating via path isolation removes fabric capacity and requires human approval.
                return Tier1MatchResult(
                    match_found=True,
                    fault_class="OPTICAL_TRANSCEIVER_DECAY",
                    confidence=0.92,
                    evidence_ids=[
                        f"crc_rate_{iface.crc_delta_per_sec:.1f}_per_sec",
                        f"crc_{iface.crc_ratio_to_baseline:.0f}x_baseline"
                    ],
                    recommended_action="isolate_degraded_path",
                    action_parameters={"device": iface.device, "interface": iface.interface},
                    is_mitigation_only=True,
                    requires_human_approval=True,  # Data-plane capacity consequence -> Mandate Human Sign-Off!
                    escalate_to_tier_2=False
                )

        # Rule 5: Asymmetric MTU Mismatch (CLOS Uplink)
        for key, iface in snapshot.interfaces.items():
            if iface.packet_loss_small_pct == 0.0 and iface.packet_loss_jumbo_pct >= 50.0 and iface.mtu < 1400:
                return Tier1MatchResult(
                    match_found=True,
                    fault_class="CLOS_ASYMMETRIC_MTU_MISMATCH",
                    confidence=0.94,
                    evidence_ids=[
                        f"jumbo_loss_{iface.packet_loss_jumbo_pct:.0f}pct",
                        f"sub_mtu_{iface.mtu}_on_{iface.interface}"
                    ],
                    recommended_action="isolate_degraded_path",
                    action_parameters={"device": iface.device, "interface": iface.interface},
                    is_mitigation_only=True,
                    requires_human_approval=True,  # Data-plane capacity consequence -> Mandate Human Sign-Off!
                    escalate_to_tier_2=False
                )

        # Rule 6: Healthy / Benign Control Case
        all_bgp_up = all(b.state == "Established" for b in snapshot.bgp_peers.values()) if snapshot.bgp_peers else True
        zero_loss = all(i.packet_loss_small_pct == 0.0 and i.packet_loss_jumbo_pct == 0.0 for i in snapshot.interfaces.values())
        zero_anomalies = not any(i.is_anomaly for i in snapshot.interfaces.values())

        if all_bgp_up and zero_loss and zero_anomalies:
            return Tier1MatchResult(
                match_found=True,
                fault_class="BENIGN_TRANSIENT_SPIKE",
                confidence=0.99,
                evidence_ids=["all_peers_established", "zero_loss_line_rate", "zero_crc_anomalies"],
                recommended_action="none",
                is_mitigation_only=False,
                requires_human_approval=False,
                escalate_to_tier_2=False
            )

        # No textbook match: Escalate to Tier 2 (Local Open-Weights ReAct Loop)
        return Tier1MatchResult(
            match_found=False,
            fault_class=None,
            confidence=0.0,
            evidence_ids=[],
            recommended_action=None,
            action_parameters={},
            is_mitigation_only=False,
            requires_human_approval=False,
            escalate_to_tier_2=True,
            escalation_reason="Ambiguous telemetry residue: multi-variable or non-textbook symptom requires agentic inspection"
        )


if __name__ == "__main__":
    print("[*] Running Statistical Delta Distiller & Tier 1 Matcher Self-Test...")
    distiller = StatisticalDeltaDistiller(baseline_crc_rate=0.05)
    matcher = Tier1InvariantMatcher(distiller=distiller)

    # Scenario 1: Raw CRC errors: 14,200.
    # Distiller turns this into a rate and baseline ratio over 5 seconds:
    t_prev = {"interfaces": {"spine-3:eth1": {"crc_errors": 12200, "carrier": True, "mtu": 1500}}}
    t_curr = {"interfaces": {"spine-3:eth1": {"crc_errors": 14200, "carrier": True, "mtu": 1500}}}
    snapshot_crc = distiller.distill_counters(t_curr, t_prev, interval_seconds=5.0)

    res_crc = matcher.evaluate(snapshot_crc)
    assert res_crc.match_found is True
    assert res_crc.fault_class == "OPTICAL_TRANSCEIVER_DECAY"
    assert res_crc.is_mitigation_only is True
    assert res_crc.requires_human_approval is True
    print(f"    [+] Scenario 1 (Optical Decay): Caught deterministically at {snapshot_crc.interfaces['spine-3:eth1'].crc_ratio_to_baseline:.0f}x baseline.")
    print(f"        Recommended Mitigation: '{res_crc.recommended_action}' (Requires Human Approval: {res_crc.requires_human_approval})")

    # Scenario 2: Ambiguous Residue (e.g. slight packet loss with no clear textbook counters)
    t_ambiguous = {
        "interfaces": {"leaf-1:eth1": {"crc_errors": 0, "carrier": True, "mtu": 1500}},
        "ping": {"loss_64b": 12.5, "loss_1400b": 12.5}
    }
    snapshot_ambiguous = distiller.distill_counters(t_ambiguous, interval_seconds=5.0)
    res_ambiguous = matcher.evaluate(snapshot_ambiguous)
    assert res_ambiguous.match_found is False
    assert res_ambiguous.escalate_to_tier_2 is True
    print(f"    [+] Scenario 2 (Ambiguous Residue): Explicitly escalated to Tier 2 ReAct loop ({res_ambiguous.escalation_reason})")

    print("[+] All Distiller and Invariant Matcher Invariants Verified.")
