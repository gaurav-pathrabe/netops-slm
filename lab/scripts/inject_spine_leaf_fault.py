#!/usr/bin/env python3
"""
inject_spine_leaf_fault.py - NetOps-SLM Phase 2 CLOS Fault Injection Engine

Supports:
1. spine_link_failure: Brings down leaf-1:eth1 (link to spine-1) -> Tests single-path failover via spine-2.
2. spine_mtu_mismatch: Drops MTU to 1200 on spine-1:eth1 -> Tests asymmetric jumbo packet drops.
3. spine_route_blackhole: Filters 10.77.2.0/24 advertisement on spine-1 -> Tests ECMP partial blackhole.
4. bgp_flapping: Flaps the BGP neighbor 3 times in 15s -> Triggers Invariant 1 (Anti-Oscillation Flap Guard).
5. restore: Recovers all links, MTUs, and BGP configurations back to healthy baseline.
"""

import sys
import argparse
import subprocess
import time

PREFIX = "clab-netops-spine-leaf-lab-"
SPINE_1 = f"{PREFIX}spine-1"
SPINE_2 = f"{PREFIX}spine-2"
LEAF_1 = f"{PREFIX}leaf-1"
LEAF_2 = f"{PREFIX}leaf-2"


def run_cmd(cmd_list):
    res = subprocess.run(cmd_list, capture_output=True, text=True)
    return res.returncode, res.stdout.strip(), res.stderr.strip()


def inject_link_failure():
    print("[*] Injecting Fault: Severing link leaf-1 <-> spine-1 (downing leaf-1:eth1)...")
    rc, out, err = run_cmd(["docker", "exec", LEAF_1, "ip", "link", "set", "dev", "eth1", "down"])
    if rc == 0:
        print("[+] Link leaf-1:eth1 is DOWN. Traffic should failover completely to spine-2 via ECMP resilience.")
    else:
        print(f"[-] Error downing link: {err}")


def inject_mtu_mismatch():
    print("[*] Injecting Fault: Asymmetric MTU mismatch on spine-1:eth1 (setting MTU=1200, fabric is 1400)...")
    rc, out, err = run_cmd(["docker", "exec", SPINE_1, "ip", "link", "set", "dev", "eth1", "mtu", "1200"])
    if rc == 0:
        print("[+] MTU on spine-1:eth1 set to 1200. Standard small ICMP will pass; large payload packets will drop.")
    else:
        print(f"[-] Error setting MTU: {err}")


def inject_route_blackhole():
    print("[*] Injecting Fault: Filtering route 10.77.2.0/24 on spine-1 (creating ECMP blackhole)...")
    cmds = [
        "configure terminal",
        "access-list DENY_LEAF2_ROUTE deny 10.77.2.0/24",
        "access-list DENY_LEAF2_ROUTE permit any",
        "route-map RM_DROP_LEAF2 deny 10",
        " match ip address DENY_LEAF2_ROUTE",
        "route-map RM_DROP_LEAF2 permit 20",
        "router bgp 65100",
        " address-family ipv4 unicast",
        "  neighbor 10.77.0.1 route-map RM_DROP_LEAF2 out",
        " exit-address-family",
        "exit",
        "clear ip bgp 10.77.0.1 soft out"
    ]
    script = "\n".join(cmds)
    rc, out, err = run_cmd(["docker", "exec", SPINE_1, "vtysh", "-c", script])
    if rc == 0:
        print("[+] Route filter applied on spine-1. Leaf-1 now receives 10.77.2.0/24 only via spine-2.")
    else:
        print(f"[-] Error applying route filter: {err}")


def inject_flapping():
    print("[*] Injecting Fault: Simulating optical link flapping (3 toggles in 15 seconds)...")
    for i in range(1, 4):
        print(f"  --> Flap cycle {i}/3: Setting leaf-1:eth1 DOWN")
        run_cmd(["docker", "exec", LEAF_1, "ip", "link", "set", "dev", "eth1", "down"])
        time.sleep(2)
        print(f"  --> Flap cycle {i}/3: Setting leaf-1:eth1 UP")
        run_cmd(["docker", "exec", LEAF_1, "ip", "link", "set", "dev", "eth1", "up"])
        time.sleep(2)
    print("[+] Flap cycle completed. Invariant 1 (Flap Damping Guard) should flag this oscillation.")


def restore_fabric():
    print("[*] Restoring CLOS Fabric to healthy baseline...")
    # 1. Ensure all interfaces are UP with MTU 1400
    for node, iface in [(LEAF_1, "eth1"), (LEAF_1, "eth2"), (LEAF_1, "eth3"),
                        (LEAF_2, "eth1"), (LEAF_2, "eth2"), (LEAF_2, "eth3"),
                        (SPINE_1, "eth1"), (SPINE_1, "eth2"),
                        (SPINE_2, "eth1"), (SPINE_2, "eth2")]:
        run_cmd(["docker", "exec", node, "ip", "link", "set", "dev", iface, "up"])
        run_cmd(["docker", "exec", node, "ip", "link", "set", "dev", iface, "mtu", "1400"])

    # 2. Reset BGP route-maps on spine-1
    reset_bgp = [
        "configure terminal",
        "router bgp 65100",
        " address-family ipv4 unicast",
        "  no neighbor 10.77.0.1 route-map RM_DROP_LEAF2 out",
        " exit-address-family",
        "no route-map RM_DROP_LEAF2",
        "no access-list DENY_LEAF2_ROUTE",
        "exit",
        "clear ip bgp * soft"
    ]
    run_cmd(["docker", "exec", SPINE_1, "vtysh", "-c", "\n".join(reset_bgp)])
    print("[+] Fabric restored. Waiting 8s for BGP convergence...")
    time.sleep(8)
    print("[+] Fabric ready.")


def main():
    parser = argparse.ArgumentParser(description="CLOS Fabric Fault Injection")
    parser.add_argument(
        "fault",
        choices=["spine_link_failure", "spine_mtu_mismatch", "spine_route_blackhole", "bgp_flapping", "restore"],
        help="Fault type to inject or restore"
    )
    args = parser.parse_args()

    if args.fault == "spine_link_failure":
        inject_link_failure()
    elif args.fault == "spine_mtu_mismatch":
        inject_mtu_mismatch()
    elif args.fault == "spine_route_blackhole":
        inject_route_blackhole()
    elif args.fault == "bgp_flapping":
        inject_flapping()
    elif args.fault == "restore":
        restore_fabric()


if __name__ == "__main__":
    main()
