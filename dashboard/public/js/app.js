/**
 * app.js - NetOps-SLM Web NOC Dashboard Interactive Client
 * Real-time event handling, topology visualization, MoLE routing, and digital twin simulation.
 */

let allIncidents = [];
let currentIncident = null;
let currentPreflightProof = null;

document.addEventListener("DOMContentLoaded", () => {
  initDashboard();
});

async function initDashboard() {
  await fetchSystemStatus();
  await fetchTopology();
  await fetchIncidents();
  setupEventListeners();
}

/**
 * 1. Fetch System Meta & Status
 */
async function fetchSystemStatus() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    const data = await res.json();
    const countEl = document.getElementById("corpus-count");
    if (countEl && data.total_episodes_indexed) {
      countEl.textContent = `${data.total_episodes_indexed} Authentic Episodes`;
    }
  } catch (err) {
    console.warn("Status fetch fallback:", err);
  }
}

/**
 * 2. Fetch Topology State & Canary Metrics
 */
async function fetchTopology() {
  try {
    const res = await fetch("/api/topology");
    if (!res.ok) return;
    const topo = await res.json();
    updateCanaryHUD(topo.canary_telemetry);
  } catch (err) {
    console.warn("Topology fetch fallback:", err);
  }
}

function updateCanaryHUD(canary) {
  if (!canary) return;
  const p56 = document.getElementById("canary-56b-status");
  const p56rtt = document.getElementById("canary-56b-rtt");
  const p1300 = document.getElementById("canary-1300b-status");
  const p1300rtt = document.getElementById("canary-1300b-rtt");

  if (p56) p56.textContent = `${canary.standard_56b_ping.loss_pct}% LOSS`;
  if (p56rtt) p56rtt.textContent = `${canary.standard_56b_ping.rtt_ms} ms`;
  if (p1300) p1300.textContent = `${canary.jumbo_1300b_ping.loss_pct}% LOSS`;
  if (p1300rtt) p1300rtt.textContent = canary.jumbo_1300b_ping.loss_pct > 0 ? "1300B DROPPED" : "1500B Pass";
}

/**
 * 3. Fetch Incident Registry
 */
async function fetchIncidents() {
  try {
    const res = await fetch("/api/incidents");
    if (!res.ok) return;
    allIncidents = await res.json();
    
    const select = document.getElementById("select-incident");
    select.innerHTML = '<option value="" disabled selected>-- Choose Authentic Incident --</option>';
    
    allIncidents.forEach((inc) => {
      const opt = document.createElement("option");
      opt.value = inc.id;
      opt.textContent = `[${inc.severity}] ${inc.name}`;
      select.appendChild(opt);
    });

    // Auto-select the MTU Mismatch episode as initial demo
    if (allIncidents.length > 2) {
      select.value = allIncidents[2].id;
      handleIncidentChange(allIncidents[2].id);
    }
  } catch (err) {
    console.error("Failed to load incidents:", err);
  }
}

function setupEventListeners() {
  const select = document.getElementById("select-incident");
  if (select) {
    select.addEventListener("change", (e) => handleIncidentChange(e.target.value));
  }

  const btnPreflight = document.getElementById("btn-run-preflight");
  if (btnPreflight) {
    btnPreflight.addEventListener("click", runPreFlightSimulation);
  }

  const btnExecute = document.getElementById("btn-execute-action");
  if (btnExecute) {
    btnExecute.addEventListener("click", executeAction);
  }

  const chkMode = document.getElementById("chk-one-click");
  if (chkMode) {
    chkMode.addEventListener("change", (e) => {
      const lbl = document.getElementById("lbl-mode");
      if (lbl) {
        lbl.textContent = e.target.checked ? "1-Click Approved" : "Shadow Mode";
        lbl.style.color = e.target.checked ? "var(--accent-emerald)" : "var(--text-secondary)";
      }
    });
  }

  const btnRefresh = document.getElementById("btn-refresh-topo");
  if (btnRefresh) {
    btnRefresh.addEventListener("click", async () => {
      btnRefresh.classList.add("spinning");
      await fetchTopology();
      setTimeout(() => btnRefresh.classList.remove("spinning"), 500);
    });
  }
}

/**
 * 4. Handle Incident Selection
 */
async function handleIncidentChange(incidentId) {
  const inc = allIncidents.find((i) => i.id === incidentId);
  if (!inc) return;
  currentIncident = inc;

  // Update telemetry box
  document.getElementById("incident-domain").textContent = `Domain: ${inc.domain}`;
  const sevEl = document.getElementById("incident-severity");
  sevEl.textContent = inc.severity;
  sevEl.className = `badge ${inc.severity === 'NORMAL' ? 'badge-success' : inc.severity === 'WARNING' ? 'badge-warning' : 'badge-danger'}`;
  document.getElementById("incident-snippet").textContent = inc.telemetry_snippet;

  // Visual topology annotation
  updateTopologyVisuals(inc);

  // Trigger MoLE Router Gating Network
  await routeIncidentWithMoLE(inc);
}

function updateTopologyVisuals(inc) {
  const linkSpine1Leaf1 = document.getElementById("link-spine1-leaf1");
  const linkSpine1Leaf2 = document.getElementById("link-spine1-leaf2");
  const linkSpine2Leaf1 = document.getElementById("link-spine2-leaf1");
  const linkSpine2Leaf2 = document.getElementById("link-spine2-leaf2");

  // Reset classes
  [linkSpine1Leaf1, linkSpine1Leaf2, linkSpine2Leaf1, linkSpine2Leaf2].forEach((l) => {
    if (l) l.className.baseVal = "topo-link";
  });

  const p1300 = document.getElementById("canary-1300b-status");
  const p1300rtt = document.getElementById("canary-1300b-rtt");

  if (inc.id.includes("MTU_MISMATCH")) {
    linkSpine1Leaf1.classList.add("degraded");
    linkSpine2Leaf1.classList.add("active-flow");
    linkSpine2Leaf2.classList.add("active-flow");
    if (p1300) { p1300.textContent = "100.0% LOSS"; p1300.className = "badge badge-warning"; }
    if (p1300rtt) p1300rtt.textContent = "1300B CLAMPED (1200 MTU)";
  } else if (inc.id.includes("LINK_SEVERED")) {
    linkSpine1Leaf1.classList.add("degraded");
    linkSpine2Leaf1.classList.add("active-flow");
    linkSpine2Leaf2.classList.add("active-flow");
    if (p1300) { p1300.textContent = "0.0% LOSS"; p1300.className = "badge badge-success"; }
    if (p1300rtt) p1300rtt.textContent = "1500B Pass via spine-2";
  } else if (inc.id.includes("ROUTE_BLACKHOLE")) {
    linkSpine1Leaf2.classList.add("degraded");
    linkSpine2Leaf1.classList.add("active-flow");
    linkSpine2Leaf2.classList.add("active-flow");
    if (p1300) { p1300.textContent = "50.0% LOSS"; p1300.className = "badge badge-warning"; }
    if (p1300rtt) p1300rtt.textContent = "Hash Polarized Drop";
  } else {
    // Normal ECMP flow
    linkSpine1Leaf1.classList.add("active-flow");
    linkSpine2Leaf1.classList.add("active-flow");
    if (p1300) { p1300.textContent = "0.0% LOSS"; p1300.className = "badge badge-success"; }
    if (p1300rtt) p1300rtt.textContent = "1500B Pass";
  }
}

/**
 * 5. MoLE Router Gating Dispatch
 */
async function routeIncidentWithMoLE(inc) {
  try {
    const res = await fetch("/api/route_expert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description: `${inc.name} ${inc.telemetry_snippet}` })
    });
    if (!res.ok) return;
    const data = await res.json();

    const wClos = (data.weights.expert_clos_fabric * 100).toFixed(1);
    const wBgp = (data.weights.expert_bgp_protocol * 100).toFixed(1);
    const wGate = (data.weights.expert_template_gate * 100).toFixed(1);

    document.getElementById("weight-clos").textContent = `${wClos}%`;
    document.getElementById("weight-bgp").textContent = `${wBgp}%`;
    document.getElementById("weight-gate").textContent = `${wGate}%`;

    document.getElementById("fill-clos").style.width = `${wClos}%`;
    document.getElementById("fill-bgp").style.width = `${wBgp}%`;
    document.getElementById("fill-gate").style.width = `${wGate}%`;

    document.getElementById("active-expert-name").textContent = data.selected_expert;
    document.getElementById("mole-latency-tag").textContent = `${data.dispatch_latency_ms} ms (Fast-Path)`;
  } catch (err) {
    console.error("MoLE dispatch error:", err);
  }
}

/**
 * 6. Pre-Flight Digital Twin Simulator
 */
async function runPreFlightSimulation() {
  if (!currentIncident) return;
  const btn = document.getElementById("btn-run-preflight");
  btn.textContent = "Simulating Twin...";
  btn.disabled = true;

  const payload = {
    diagnosis: currentIncident.id,
    evidence_ids: ["canary_probe_01"],
    affected_nodes: [currentIncident.parameters?.device || "spine-1"],
    action: currentIncident.recommended_action || "none",
    parameters: currentIncident.parameters || {},
    verification_checks: ["ecmp_rebalance"],
    abstain: currentIncident.abstain || false
  };

  try {
    const res = await fetch("/api/verify_preflight", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        incident_id: currentIncident.id,
        action_payload: payload,
        initial_telemetry: { anomaly_type: currentIncident.id }
      })
    });
    if (!res.ok) return;
    const proof = await res.json();
    currentPreflightProof = proof;

    // Update UI Elements
    document.getElementById("pf-reachability").textContent = proof.reachability_status === "REACHABLE" ? "PROVED (client-1 ➔ spine-2 ➔ client-2)" : "UNREACHABLE_BLACKHOLE";
    document.getElementById("pf-reachability").className = proof.reachability_status === "REACHABLE" ? "text-green" : "text-red";

    document.getElementById("pf-loop").textContent = proof.loop_free ? "ACYCLIC (0 Loops)" : "LOOP DETECTED";
    document.getElementById("pf-loop").className = proof.loop_free ? "text-green" : "text-red";

    document.getElementById("pf-blackhole").textContent = proof.blackhole_free ? "0 Blackholes" : "BLACKHOLE DETECTED";
    document.getElementById("pf-blackhole").className = proof.blackhole_free ? "text-green" : "text-red";

    document.getElementById("pf-capacity").textContent = proof.capacity_invariant_passed ? "PASSED (Spine-2 100% Ready)" : "FAILED";
    document.getElementById("pf-capacity").className = proof.capacity_invariant_passed ? "text-green" : "text-red";

    document.getElementById("pf-latency").textContent = `${proof.verification_latency_ms} ms`;
    document.getElementById("pf-sha").textContent = `${proof.cryptographic_sha256.substring(0, 16)}...`;

  } catch (err) {
    console.error("Preflight simulation error:", err);
  } finally {
    btn.textContent = "Simulate Pre-Flight Proof";
    btn.disabled = false;
  }
}

/**
 * 7. Execute Action (TypedActionGate 1-Click Approval)
 */
async function executeAction() {
  if (!currentIncident) return;
  const isOneClick = document.getElementById("chk-one-click").checked;
  const btn = document.getElementById("btn-execute-action");
  btn.disabled = true;

  const payload = {
    diagnosis: currentIncident.id,
    evidence_ids: ["canary_probe_01"],
    affected_nodes: [currentIncident.parameters?.device || "spine-1"],
    action: currentIncident.recommended_action || "none",
    parameters: currentIncident.parameters || {},
    verification_checks: ["ecmp_rebalance"],
    abstain: currentIncident.abstain || false
  };

  try {
    const res = await fetch("/api/execute_action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        incident_id: currentIncident.id,
        action_payload: payload,
        mode: isOneClick ? "one_click_approved" : "shadow",
        force_flaps: currentIncident.force_flaps || 0
      })
    });
    if (!res.ok) return;
    const data = await res.json();

    const cliBox = document.getElementById("rendered-cli-text");
    if (data.success) {
      cliBox.textContent = data.rendered_cli || "# Action safely rendered.";
      cliBox.style.color = "var(--accent-cyan)";
    } else {
      cliBox.textContent = `CRITICAL SAFETY INTERCEPTION:\n${data.errors.join("\n")}`;
      cliBox.style.color = "var(--accent-rose)";
    }
  } catch (err) {
    console.error("Execution error:", err);
  } finally {
    btn.disabled = false;
  }
}
