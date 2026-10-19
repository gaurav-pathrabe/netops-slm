"""
fault_ontology.py - NetOps Autonomous Boundary: Fault Ontology v1

Defines the formal v1 ontology matrix for network incident root causes,
observable telemetry predicates, typed remediation actions, inverse rollback actions,
and safety classification labels.

Schema mapping:
Root Cause x Observable Symptoms x Diagnostic Tools x Typed Action x Rollback x Safety Tier
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any


class SafetyTier(Enum):
    SAFE_AUTONOMOUS = "SAFE_AUTONOMOUS"          # Pre-approved for bounded closed-loop remediation
    SUPERVISED_APPROVAL = "SUPERVISED_APPROVAL"  # Propose only; requires human approval
    FORBIDDEN_AUTOMATION = "FORBIDDEN_AUTOMATION"# Lockout / Escalation only; direct automated fix prohibited


class VendorNOS(Enum):
    FRR = "frr"
    SONIC = "sonic"
    CEOS = "ceos"
    VJUNOS = "vjunos"
    SRLINUX = "srlinux"
    GENERIC = "generic"


@dataclass(frozen=True)
class FaultClassDefinition:
    fault_id: str
    category: str
    root_cause: str
    symptoms: List[str]
    observable_predicates: List[str]
    diagnostic_tools: List[str]
    typed_action: str
    rollback_action: str
    safety_tier: SafetyTier
    supported_vendors: List[VendorNOS]
    invariants: List[str]
    description: str


# 15 Standard Fault Classes covering BGP, Clos Fabric, Interfaces, MTU, Optical, Policy, & Hard Negatives
FAULT_ONTOLOGY_V1: Dict[str, FaultClassDefinition] = {
    # 1. BGP Peering Administratively Shutdown
    "BGP_NEIGHBOR_ADMIN_DOWN": FaultClassDefinition(
        fault_id="BGP_NEIGHBOR_ADMIN_DOWN",
        category="BGP_CONTROL_PLANE",
        root_cause="BGP neighbor session administratively shutdown or disabled in config.",
        symptoms=["BGP session state Idle (Admin)", "Route withdrawal across fabric"],
        observable_predicates=[
            "telemetry.bgp.peer_state == 'Idle'",
            "telemetry.bgp.admin_down == True"
        ],
        diagnostic_tools=["query_bgp_summary", "inspect_router_config"],
        typed_action="reenable_bgp_neighbor",
        rollback_action="shutdown_bgp_neighbor",
        safety_tier=SafetyTier.SAFE_AUTONOMOUS,
        supported_vendors=[VendorNOS.FRR, VendorNOS.SONIC, VendorNOS.CEOS, VendorNOS.VJUNOS],
        invariants=["Anti-flap guard: peer must not have flapped >= 2 times in 15 minutes."],
        description="Neighbor was shut down manually or by prior script; re-enable session if flap counter is clean."
    ),

    # 2. BGP Remote AS Misconfiguration
    "BGP_REMOTE_AS_MISMATCH": FaultClassDefinition(
        fault_id="BGP_REMOTE_AS_MISMATCH",
        category="BGP_CONTROL_PLANE",
        root_cause="Configured remote-as does not match the autonomous system number advertised in OPEN message.",
        symptoms=["BGP session stuck in Active or Connect", "Syslog BGP OPEN message rejection"],
        observable_predicates=[
            "telemetry.bgp.peer_state in ['Active', 'Connect']",
            "telemetry.syslog contains 'OPEN message rejected: bad peer AS'"
        ],
        diagnostic_tools=["query_bgp_summary", "inspect_syslog", "verify_asn_inventory"],
        typed_action="correct_remote_as",
        rollback_action="restore_prior_remote_as",
        safety_tier=SafetyTier.SAFE_AUTONOMOUS,
        supported_vendors=[VendorNOS.FRR, VendorNOS.SONIC, VendorNOS.CEOS, VendorNOS.VJUNOS],
        invariants=["Target ASN must match verified physical topology inventory."],
        description="Corrects remote-as to match verified fabric inventory ASN."
    ),

    # 3. Missing Prefix Origination
    "BGP_PREFIX_UNORIGINATED": FaultClassDefinition(
        fault_id="BGP_PREFIX_UNORIGINATED",
        category="ROUTING_TABLE",
        root_cause="Subnet interface is up, but network statement or redistribution is missing from BGP configuration.",
        symptoms=["Connected subnet unreachable from remote leaves", "Route missing from BGP RIB"],
        observable_predicates=[
            "telemetry.interface.state == 'up'",
            "telemetry.bgp.rib contains prefix == False"
        ],
        diagnostic_tools=["query_route_table", "query_bgp_rib", "check_canary_loss"],
        typed_action="originate_prefix",
        rollback_action="withdraw_prefix",
        safety_tier=SafetyTier.SAFE_AUTONOMOUS,
        supported_vendors=[VendorNOS.FRR, VendorNOS.SONIC, VendorNOS.CEOS],
        invariants=["Prefix must belong to authorized subnet range."],
        description="Advertises missing connected prefix into BGP IPv4 unicast."
    ),

    # 4. Asymmetric MTU Mismatch (CLOS Uplink)
    "CLOS_ASYMMETRIC_MTU_MISMATCH": FaultClassDefinition(
        fault_id="CLOS_ASYMMETRIC_MTU_MISMATCH",
        category="FABRIC_PHYSICAL",
        root_cause="Interface MTU mismatch along ECMP transit uplink (e.g. 1200 vs 1400/9000).",
        symptoms=["Small 64B ping succeeds; large jumbo ICMP / RoCE / TCP payload drops silently"],
        observable_predicates=[
            "telemetry.ping.small_payload_loss == 0.0",
            "telemetry.ping.jumbo_payload_loss > 0.0",
            "telemetry.interface.mtu_mismatch == True"
        ],
        diagnostic_tools=["check_canary_loss", "read_interface_counters", "inspect_interface_mtu"],
        typed_action="isolate_degraded_path",
        rollback_action="restore_spine_path",
        safety_tier=SafetyTier.SUPERVISED_APPROVAL,
        supported_vendors=[VendorNOS.FRR, VendorNOS.SONIC, VendorNOS.CEOS],
        invariants=["Isolating transit uplink reduces fabric capacity; requires human approval."],
        description="Path isolation is a temporary mitigation to divert jumbo traffic. Requires human authorization due to capacity/blast-radius impact."
    ),

    # 5. Severed Spine Link
    "CLOS_SPINE_LINK_SEVERED": FaultClassDefinition(
        fault_id="CLOS_SPINE_LINK_SEVERED",
        category="FABRIC_PHYSICAL",
        root_cause="Physical fiber cut or transit link administratively forced down.",
        symptoms=["ECMP path count reduced from N to N-1", "Link down alarm on leaf and spine"],
        observable_predicates=[
            "telemetry.interface.carrier == False",
            "telemetry.ecmp.active_paths == 1"
        ],
        diagnostic_tools=["read_interface_counters", "query_route_table", "query_bgp_summary"],
        typed_action="none",  # ECMP self-heals in hardware; do not flap unnecessary configs
        rollback_action="none",
        safety_tier=SafetyTier.SAFE_AUTONOMOUS,
        supported_vendors=[VendorNOS.FRR, VendorNOS.SONIC, VendorNOS.CEOS],
        invariants=["Fabric must maintain at least 1 healthy spine uplink."],
        description="Asserts hardware ECMP convergence; suppresses unnecessary control plane churn."
    ),

    # 6. ECMP Route Blackhole (Spine Route Filter)
    "CLOS_ECMP_ROUTE_BLACKHOLE": FaultClassDefinition(
        fault_id="CLOS_ECMP_ROUTE_BLACKHOLE",
        category="ROUTING_POLICY",
        root_cause="One spine filters a downstream leaf prefix while sibling spines advertise it.",
        symptoms=["Intermittent packet drop (e.g. 50% packet loss) across ECMP hash buckets"],
        observable_predicates=[
            "telemetry.ping.loss_percentage >= 40.0",
            "telemetry.ping.loss_percentage <= 60.0",
            "telemetry.spines.rib_discrepancy == True"
        ],
        diagnostic_tools=["compare_spine_ribs", "check_canary_loss", "inspect_route_maps"],
        typed_action="drain_spine_traffic",
        rollback_action="undrain_spine_traffic",
        safety_tier=SafetyTier.SUPERVISED_APPROVAL,
        supported_vendors=[VendorNOS.FRR, VendorNOS.SONIC, VendorNOS.CEOS],
        invariants=["Remaining spine capacity must exceed current aggregate fabric throughput."],
        description="Gracefully drains affected spine out of ECMP forwarding until route policy is corrected."
    ),

    # 7. Optical Transceiver Decay / High CRC Errors
    "OPTICAL_TRANSCEIVER_DECAY": FaultClassDefinition(
        fault_id="OPTICAL_TRANSCEIVER_DECAY",
        category="PHYSICAL_LAYER",
        root_cause="Failing optical laser, dirty connector, or high BER causing CRC drops without link down.",
        symptoms=["Elevated CRC/FCS error counters on physical switch port; micro-burst drops"],
        observable_predicates=[
            "telemetry.interface.fcs_errors_per_sec > 100",
            "telemetry.interface.carrier == True"
        ],
        diagnostic_tools=["read_interface_counters", "inspect_dom_optical_power"],
        typed_action="isolate_degraded_path",
        rollback_action="restore_spine_path",
        safety_tier=SafetyTier.SUPERVISED_APPROVAL,
        supported_vendors=[VendorNOS.SONIC, VendorNOS.CEOS, VendorNOS.VJUNOS],
        invariants=["Path isolation is a temporary mitigation; root fix is physical optic replacement."],
        description="Raises alarm and recommends physical transceiver replacement. Optional path isolation mitigation requires human supervisor approval due to capacity blast-radius."
    ),

    # 8. Rapid Route Flapping (Anti-Oscillation Guard)
    "BGP_RAPID_ROUTE_FLAPPING": FaultClassDefinition(
        fault_id="BGP_RAPID_ROUTE_FLAPPING",
        category="STABILITY_GUARD",
        root_cause="Intermittent BGP session flapping >= 2 times in 15 minutes.",
        symptoms=["Route flap damping alarms", "Control plane CPU spikes"],
        observable_predicates=[
            "telemetry.bgp.flaps_in_window >= 2"
        ],
        diagnostic_tools=["inspect_flap_history", "query_bgp_summary"],
        typed_action="none",  # Lockout automation; prevent internet/fabric flap storm
        rollback_action="none",
        safety_tier=SafetyTier.FORBIDDEN_AUTOMATION,
        supported_vendors=[VendorNOS.FRR, VendorNOS.SONIC, VendorNOS.CEOS, VendorNOS.VJUNOS],
        invariants=["Automation must NEVER repeatedly re-enable a flapping peer."],
        description="Mandatory lockout. Suppresses automatic intervention to prevent global route flap storms."
    ),

    # 9. Control Plane BGP Route Reflector Loop
    "BGP_ROUTE_REFLECTOR_LOOP": FaultClassDefinition(
        fault_id="BGP_ROUTE_REFLECTOR_LOOP",
        category="BGP_CONTROL_PLANE",
        root_cause="Cluster-ID or originator-ID misconfiguration causing routing information loop.",
        symptoms=["BGP routes withdrawn due to originator-ID loop detection", "Unstable prefixes"],
        observable_predicates=[
            "telemetry.syslog contains 'BGP: route dropped due to loop detection'"
        ],
        diagnostic_tools=["query_bgp_rib", "inspect_router_config"],
        typed_action="none",
        rollback_action="none",
        safety_tier=SafetyTier.SUPERVISED_APPROVAL,
        supported_vendors=[VendorNOS.FRR, VendorNOS.CEOS, VendorNOS.VJUNOS],
        invariants=["Must not modify cluster ID without human change review."],
        description="Route reflector cluster loop detected; requires supervised human topology review."
    ),

    # 10. ACL Misconfiguration Drop
    "ACL_MISCONFIGURED_DROP": FaultClassDefinition(
        fault_id="ACL_MISCONFIGURED_DROP",
        category="SECURITY_POLICY",
        root_cause="Access-list or firewall filter erroneously dropping legitimate inter-subnet traffic.",
        symptoms=["100% loss for specific protocol or port", "ACL hit counters incrementing rapidly"],
        observable_predicates=[
            "telemetry.acl.drop_counter_delta > 0",
            "telemetry.route_table.has_route == True"
        ],
        diagnostic_tools=["read_acl_counters", "inspect_router_config"],
        typed_action="none",
        rollback_action="none",
        safety_tier=SafetyTier.SUPERVISED_APPROVAL,
        supported_vendors=[VendorNOS.SONIC, VendorNOS.CEOS, VendorNOS.VJUNOS],
        invariants=["Security policy mutations require human sign-off."],
        description="ACL policy drop detected; proposes filter correction for human supervisor authorization."
    ),

    # 11. QoS Buffer Exhaustion / RoCE Incast
    "QOS_BUFFER_EXHAUSTION_INCAST": FaultClassDefinition(
        fault_id="QOS_BUFFER_EXHAUSTION_INCAST",
        category="AI_FABRIC_QOS",
        root_cause="All-to-all GPU collective communication causing egress buffer congestion and PFC deadlocks.",
        symptoms=["PFC pause frames generated", "ECN marking rate spikes", "Tail latency inflation"],
        observable_predicates=[
            "telemetry.qos.pfc_rx_pause_frames > 1000",
            "telemetry.qos.ecn_marked_packets > 5000"
        ],
        diagnostic_tools=["read_qos_buffer_watermarks", "read_interface_counters"],
        typed_action="none",
        rollback_action="none",
        safety_tier=SafetyTier.SUPERVISED_APPROVAL,
        supported_vendors=[VendorNOS.SONIC, VendorNOS.CEOS],
        invariants=["Buffer partition adjustments must not violate lossless storage SLOs."],
        description="AI fabric buffer congestion detected; identifies offending flows and notifies scheduler."
    ),

    # 12. VLAN / VXLAN VNI Mapping Desync
    "VXLAN_VNI_MISMATCH": FaultClassDefinition(
        fault_id="VXLAN_VNI_MISMATCH",
        category="OVERLAY_EVPN",
        root_cause="VLAN-to-VNI mapping discrepancy between leaf switches.",
        symptoms=["Layer-2 overlay adjacency fails", "ARP unresolved across leaf VTEPs"],
        observable_predicates=[
            "telemetry.evpn.vni_mapped == False",
            "telemetry.arp.unresolved == True"
        ],
        diagnostic_tools=["query_evpn_vni", "inspect_router_config"],
        typed_action="none",
        rollback_action="none",
        safety_tier=SafetyTier.SUPERVISED_APPROVAL,
        supported_vendors=[VendorNOS.SONIC, VendorNOS.CEOS, VendorNOS.FRR],
        invariants=["VNI allocations must match data center IPAM/DCIM registry."],
        description="Overlay VNI desynchronization detected; requires supervised human alignment."
    ),

    # 13. LACP Port Channel Desync
    "LACP_PORT_CHANNEL_DESYNC": FaultClassDefinition(
        fault_id="LACP_PORT_CHANNEL_DESYNC",
        category="LINK_AGGREGATION",
        root_cause="LACP rate fast/slow mismatch or system priority discrepancy across MLAG/vPC pair.",
        symptoms=["Port suspended from bundle", "Asymmetric bandwidth"],
        observable_predicates=[
            "telemetry.lacp.port_state == 'suspended'",
            "telemetry.lacp.partner_sync == False"
        ],
        diagnostic_tools=["query_lacp_state", "read_interface_counters"],
        typed_action="none",
        rollback_action="none",
        safety_tier=SafetyTier.SUPERVISED_APPROVAL,
        supported_vendors=[VendorNOS.SONIC, VendorNOS.CEOS],
        invariants=["MLAG core consistency checks must pass."],
        description="LACP negotiation failure detected; proposes configuration synchronization."
    ),

    # 14. Underlay IGP (OSPF/IS-IS) Area Mismatch
    "UNDERLAY_IGP_AREA_MISMATCH": FaultClassDefinition(
        fault_id="UNDERLAY_IGP_AREA_MISMATCH",
        category="UNDERLAY_CONTROL_PLANE",
        root_cause="OSPF area ID or IS-IS level mismatch between spine and leaf.",
        symptoms=["Underlay neighbor fails to reach FULL/Adjacency", "Loopback addresses unreachable"],
        observable_predicates=[
            "telemetry.ospf.neighbor_state in ['Init', '2-Way', 'ExStart']"
        ],
        diagnostic_tools=["query_ospf_neighbors", "inspect_router_config"],
        typed_action="none",
        rollback_action="none",
        safety_tier=SafetyTier.SUPERVISED_APPROVAL,
        supported_vendors=[VendorNOS.FRR, VendorNOS.CEOS, VendorNOS.VJUNOS],
        invariants=["Underlay IGP must match fabric architecture specification."],
        description="Underlay IGP adjacency stall detected; identifies area mismatch."
    ),

    # 15. Benign Transient Traffic Spike (Hard Negative Control)
    "BENIGN_TRANSIENT_SPIKE": FaultClassDefinition(
        fault_id="BENIGN_TRANSIENT_SPIKE",
        category="CONTROL_HARD_NEGATIVE",
        root_cause="Normal bursty workload (e.g. backup, model checkpoint sync) without protocol error.",
        symptoms=["Transient interface utilization spike > 80% without packet loss or link flaps"],
        observable_predicates=[
            "telemetry.interface.utilization_pct > 80.0",
            "telemetry.interface.packet_loss_pct == 0.0",
            "telemetry.bgp.all_peers_established == True"
        ],
        diagnostic_tools=["check_canary_loss", "read_interface_counters", "query_bgp_summary"],
        typed_action="none",  # Mandatory abstention
        rollback_action="none",
        safety_tier=SafetyTier.SAFE_AUTONOMOUS,
        supported_vendors=[VendorNOS.FRR, VendorNOS.SONIC, VendorNOS.CEOS, VendorNOS.VJUNOS, VendorNOS.SRLINUX],
        invariants=["Automation must NEVER intervene during benign operational fluctuations."],
        description="Hard negative control episode. Verifies 0% false-positive actuation rate."
    )
}


def get_fault_class(fault_id: str) -> Optional[FaultClassDefinition]:
    """Retrieves a formal fault class definition by ID."""
    return FAULT_ONTOLOGY_V1.get(fault_id)


def list_fault_classes() -> List[str]:
    """Lists all 15 supported fault class IDs."""
    return list(FAULT_ONTOLOGY_V1.keys())


def get_autonomous_fault_classes() -> List[str]:
    """Returns fault classes eligible for closed-loop safe autonomous remediation."""
    return [
        fid for fid, defn in FAULT_ONTOLOGY_V1.items()
        if defn.safety_tier == SafetyTier.SAFE_AUTONOMOUS and defn.typed_action != "none"
    ]
