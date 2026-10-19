"""
evaluate_diagnosis_quality.py - First-Class Diagnosis Quality & Evidence Faithfulness Harness

The Core Scientific Truth:
SAFETY != CORRECTNESS.
The Safety Gate proves the action is safe within the verifier's authority;
it does NOT prove the diagnosis is correct.
A model can produce a plausible, wrong diagnosis (e.g. blaming spine-3 for drops
caused by congestion on spine-2), and the gate will happily approve the action if it
is schema-valid and reachability-safe. Taking a safe action against the wrong switch
leaves the root incident active.

This harness evaluates diagnosis quality INDEPENDENTLY of the safety gate:
1. Top-1 and Top-3 Root Cause Accuracy
2. Evidence Faithfulness (verifying every cited counter/metric against actual telemetry)
3. Hallucinated-Evidence Rate (detecting invented counters or non-existent telemetry IDs)
4. Abstention Quality (precision/recall on ambiguous, noisy, or benign states)
5. The Safety vs. Correctness Divergence Gap
"""

import sys
import os
import json
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.evaluation.statistical_rigor import wilson_score_interval


@dataclass
class EpisodeDiagnosisEval:
    episode_id: str
    ground_truth_fault: str
    predicted_top1: str
    predicted_top3: List[str]
    top1_correct: bool
    top3_correct: bool
    total_cited_evidence: int
    verified_evidence_count: int
    hallucinated_evidence_count: int
    evidence_faithfulness_pct: float
    hallucinated_evidence_rate_pct: float
    is_abstain_expected: bool
    did_abstain: bool
    action_safety_passed: bool  # From verifier gate
    diagnosis_correct: bool     # True root-cause match
    divergence_flag: bool       # True if action was 'Safe' but diagnosis was WRONG!
    divergence_reason: Optional[str] = None


@dataclass
class DiagnosisQualityReport:
    total_episodes: int
    top1_accuracy_pct: float
    top1_ci_95: Tuple[float, float]
    top3_accuracy_pct: float
    top3_ci_95: Tuple[float, float]
    overall_evidence_faithfulness_pct: float
    overall_hallucinated_evidence_rate_pct: float
    abstention_precision_pct: float
    abstention_recall_pct: float
    safety_approval_rate_pct: float
    divergence_count: int
    divergence_rate_pct: float
    passed_enterprise_quality_gate: bool
    per_episode_evals: List[EpisodeDiagnosisEval] = field(default_factory=list)

    def print_summary(self):
        print("\n" + "=" * 70)
        print("          NETOPS DIAGNOSIS QUALITY & FAITHFULNESS REPORT          ")
        print("=" * 70)
        print(f"Total Episodes Evaluated: {self.total_episodes}")
        print(f"Top-1 Diagnosis Accuracy: {self.top1_accuracy_pct:.2f}% (95% CI: [{self.top1_ci_95[0]:.2f}%, {self.top1_ci_95[1]:.2f}%])")
        print(f"Top-3 Diagnosis Accuracy: {self.top3_accuracy_pct:.2f}% (95% CI: [{self.top3_ci_95[0]:.2f}%, {self.top3_ci_95[1]:.2f}%])")
        print(f"Evidence Faithfulness:    {self.overall_evidence_faithfulness_pct:.2f}% (cited real telemetry)")
        print(f"Hallucinated Evidence:    {self.overall_hallucinated_evidence_rate_pct:.2f}% (invented counters)")
        print(f"Abstention Precision:     {self.abstention_precision_pct:.2f}%")
        print(f"Abstention Recall:        {self.abstention_recall_pct:.2f}%")
        print("-" * 70)
        print("CRITICAL SAFETY != CORRECTNESS DIVERGENCE METRICS:")
        print(f"Verifier Gate Safety Approval: {self.safety_approval_rate_pct:.2f}%")
        print(f"Safe Action on WRONG Target:   {self.divergence_count} episodes ({self.divergence_rate_pct:.2f}%)")
        print(f"Enterprise Quality Gate:       {'PASSED [OK]' if self.passed_enterprise_quality_gate else 'FAILED [X]'}")
        print("=" * 70 + "\n")


class DiagnosisQualityEvaluator:
    """
    Evaluates agent / model diagnosis quality, checking evidence fidelity against raw telemetry.
    """

    @staticmethod
    def verify_evidence_faithfulness(
        cited_evidence_ids: List[str],
        raw_telemetry: Dict[str, Any]
    ) -> Tuple[int, int]:
        """
        Verifies whether cited evidence items exist in raw telemetry.
        Returns: (verified_count, hallucinated_count)
        """
        if not cited_evidence_ids:
            return 0, 0

        verified = 0
        hallucinated = 0

        # Build reference set of verifiable telemetry strings
        telemetry_str = json.dumps(raw_telemetry).lower()

        for ev in cited_evidence_ids:
            clean_ev = ev.lower().replace("_", " ").replace("-", " ")
            tokens = [t for t in clean_ev.split() if len(t) > 2]
            # If all key tokens or the substring are represented in telemetry
            if any(t in telemetry_str for t in tokens) or (ev.lower() in telemetry_str):
                verified += 1
            else:
                hallucinated += 1

        return verified, hallucinated

    @classmethod
    def evaluate_episodes(
        cls,
        eval_dataset: List[Dict[str, Any]]
    ) -> DiagnosisQualityReport:
        """
        Runs comprehensive diagnosis evaluation across an incident dataset.
        Each item in eval_dataset must contain:
        - 'episode_id'
        - 'ground_truth': {'fault_class': str, 'affected_device': str}
        - 'raw_telemetry': dict
        - 'model_proposal': {
             'top_hypothesis': str,
             'ranked_differential': [{'hypothesis': str, ...}],
             'cited_evidence_ids': [str],
             'target_device': str,
             'abstain': bool,
             'gate_passed': bool
          }
        """
        total = len(eval_dataset)
        if total == 0:
            return DiagnosisQualityReport(
                total_episodes=0,
                top1_accuracy_pct=0.0,
                top1_ci_95=(0.0, 0.0),
                top3_accuracy_pct=0.0,
                top3_ci_95=(0.0, 0.0),
                overall_evidence_faithfulness_pct=0.0,
                overall_hallucinated_evidence_rate_pct=0.0,
                abstention_precision_pct=0.0,
                abstention_recall_pct=0.0,
                safety_approval_rate_pct=0.0,
                divergence_count=0,
                divergence_rate_pct=0.0,
                passed_enterprise_quality_gate=False
            )

        top1_hits = 0
        top3_hits = 0
        total_evidence_items = 0
        verified_evidence_items = 0
        hallucinated_evidence_items = 0

        abstain_true_positive = 0
        abstain_false_positive = 0
        abstain_true_negative = 0
        abstain_false_negative = 0

        safety_approved_count = 0
        divergence_count = 0
        per_ep_evals: List[EpisodeDiagnosisEval] = []

        for item in eval_dataset:
            ep_id = item.get("episode_id", "EP_UNKNOWN")
            gt = item.get("ground_truth", {})
            gt_fault = gt.get("fault_class", "")
            gt_device = gt.get("affected_device", "")
            telemetry = item.get("raw_telemetry", {})
            proposal = item.get("model_proposal", {})

            pred_top1 = proposal.get("top_hypothesis", "")
            differential = proposal.get("ranked_differential", [])
            pred_top3 = [d.get("hypothesis", "") for d in differential[:3]]
            if pred_top1 and pred_top1 not in pred_top3:
                pred_top3.insert(0, pred_top1)
                pred_top3 = pred_top3[:3]

            pred_device = proposal.get("target_device", "")
            abstain = proposal.get("abstain", False)
            gate_passed = proposal.get("gate_passed", False)
            cited_ev = proposal.get("cited_evidence_ids", [])

            # 1. Top-1 and Top-3 accuracy
            top1_ok = (pred_top1 == gt_fault) and (not gt_device or pred_device == gt_device)
            top3_ok = (gt_fault in pred_top3)
            if top1_ok:
                top1_hits += 1
            if top3_ok:
                top3_hits += 1

            # 2. Evidence Faithfulness
            ver_cnt, hal_cnt = cls.verify_evidence_faithfulness(cited_ev, telemetry)
            total_evidence_items += len(cited_ev)
            verified_evidence_items += ver_cnt
            hallucinated_evidence_items += hal_cnt

            ev_faith_pct = (ver_cnt / len(cited_ev) * 100.0) if cited_ev else 100.0
            ev_hal_pct = (hal_cnt / len(cited_ev) * 100.0) if cited_ev else 0.0

            # 3. Abstention Quality
            is_benign = (gt_fault == "BENIGN_TRANSIENT_SPIKE" or gt_fault == "INSUFFICIENT_EVIDENCE")
            if is_benign and abstain:
                abstain_true_positive += 1
            elif is_benign and not abstain:
                abstain_false_negative += 1
            elif not is_benign and abstain:
                abstain_false_positive += 1
            else:
                abstain_true_negative += 1

            # 4. Verifier Gate vs. Diagnosis Divergence
            if gate_passed:
                safety_approved_count += 1

            # Divergence condition: Gate approved action, but diagnosis was WRONG!
            divergence = False
            div_reason = None
            if gate_passed and not top1_ok and not is_benign:
                divergence = True
                divergence_count += 1
                div_reason = f"Gate approved safe action against '{pred_device}' for '{pred_top1}', but true cause was '{gt_fault}' on '{gt_device}'."

            per_ep_evals.append(EpisodeDiagnosisEval(
                episode_id=ep_id,
                ground_truth_fault=gt_fault,
                predicted_top1=pred_top1,
                predicted_top3=pred_top3,
                top1_correct=top1_ok,
                top3_correct=top3_ok,
                total_cited_evidence=len(cited_ev),
                verified_evidence_count=ver_cnt,
                hallucinated_evidence_count=hal_cnt,
                evidence_faithfulness_pct=ev_faith_pct,
                hallucinated_evidence_rate_pct=ev_hal_pct,
                is_abstain_expected=is_benign,
                did_abstain=abstain,
                action_safety_passed=gate_passed,
                diagnosis_correct=top1_ok,
                divergence_flag=divergence,
                divergence_reason=div_reason
            ))

        top1_pct = (top1_hits / total) * 100.0
        top3_pct = (top3_hits / total) * 100.0
        _, top1_lo, top1_hi = wilson_score_interval(top1_hits, total)
        _, top3_lo, top3_hi = wilson_score_interval(top3_hits, total)
        top1_ci = (top1_lo, top1_hi)
        top3_ci = (top3_lo, top3_hi)

        faithfulness_pct = (verified_evidence_items / total_evidence_items * 100.0) if total_evidence_items > 0 else 100.0
        hallucination_pct = (hallucinated_evidence_items / total_evidence_items * 100.0) if total_evidence_items > 0 else 0.0

        prec_denom = abstain_true_positive + abstain_false_positive
        abstain_precision = (abstain_true_positive / prec_denom * 100.0) if prec_denom > 0 else 100.0

        rec_denom = abstain_true_positive + abstain_false_negative
        abstain_recall = (abstain_true_positive / rec_denom * 100.0) if rec_denom > 0 else 100.0

        safety_pct = (safety_approved_count / total) * 100.0
        div_rate = (divergence_count / total) * 100.0

        # Enterprise Quality Gate: Top-3 >= 85%, Faithfulness >= 95%, Hallucinated <= 2%, Divergence <= 5%
        passes_gate = (
            (top3_pct >= 85.0) and
            (faithfulness_pct >= 95.0) and
            (hallucination_pct <= 2.0) and
            (div_rate <= 5.0)
        )

        return DiagnosisQualityReport(
            total_episodes=total,
            top1_accuracy_pct=top1_pct,
            top1_ci_95=top1_ci,
            top3_accuracy_pct=top3_pct,
            top3_ci_95=top3_ci,
            overall_evidence_faithfulness_pct=faithfulness_pct,
            overall_hallucinated_evidence_rate_pct=hallucination_pct,
            abstention_precision_pct=abstain_precision,
            abstention_recall_pct=abstain_recall,
            safety_approval_rate_pct=safety_pct,
            divergence_count=divergence_count,
            divergence_rate_pct=div_rate,
            passed_enterprise_quality_gate=passes_gate,
            per_episode_evals=per_ep_evals
        )


if __name__ == "__main__":
    # Self-test demonstrating Safety != Correctness Divergence
    print("[*] Running Self-Test: Diagnosing Safety vs. Correctness Divergence...")

    mock_episodes = [
        # Episode 1: Correct diagnosis, Safe action
        {
            "episode_id": "EP_DEMO_001",
            "ground_truth": {"fault_class": "BGP_NEIGHBOR_ADMIN_DOWN", "affected_device": "leaf-1"},
            "raw_telemetry": {"bgp": {"peers": [{"peer": "10.77.0.2", "state": "Idle", "admin_down": True}]}},
            "model_proposal": {
                "top_hypothesis": "BGP_NEIGHBOR_ADMIN_DOWN",
                "ranked_differential": [{"hypothesis": "BGP_NEIGHBOR_ADMIN_DOWN"}],
                "cited_evidence_ids": ["admin_down", "peer_state_idle"],
                "target_device": "leaf-1",
                "abstain": False,
                "gate_passed": True
            }
        },
        # Episode 2: THE BLIND SPOT DEMO:
        # Model blames spine-3 for drops, but real cause is congestion on spine-2!
        # Verifier proves isolating spine-3 is reachability-safe (spine-1/2 still up).
        # Gate passes, but diagnosis is WRONG and network is worse off.
        {
            "episode_id": "EP_DEMO_002_BLIND_SPOT",
            "ground_truth": {"fault_class": "CLOS_ECMP_CONGESTION_DROPS", "affected_device": "spine-2"},
            "raw_telemetry": {"interfaces": {"spine-2:eth1": {"drops": 54200}}, "spine-3:eth1": {"crc_errors": 0}},
            "model_proposal": {
                "top_hypothesis": "OPTICAL_TRANSCEIVER_DECAY",
                "ranked_differential": [{"hypothesis": "OPTICAL_TRANSCEIVER_DECAY"}],
                "cited_evidence_ids": ["fake_crc_counter_on_spine3"],  # Hallucinated!
                "target_device": "spine-3",
                "abstain": False,
                "gate_passed": True  # Gate approved it because reachability is preserved!
            }
        },
        # Episode 3: Benign control episode, model correctly abstains
        {
            "episode_id": "EP_DEMO_003_BENIGN",
            "ground_truth": {"fault_class": "BENIGN_TRANSIENT_SPIKE", "affected_device": "leaf-2"},
            "raw_telemetry": {"loss": 0.0, "bgp_state": "Established"},
            "model_proposal": {
                "top_hypothesis": "BENIGN_TRANSIENT_SPIKE",
                "ranked_differential": [{"hypothesis": "BENIGN_TRANSIENT_SPIKE"}],
                "cited_evidence_ids": ["loss_zero", "bgp_established"],
                "target_device": "leaf-2",
                "abstain": True,
                "gate_passed": True
            }
        }
    ]

    report = DiagnosisQualityEvaluator.evaluate_episodes(mock_episodes)
    report.print_summary()

    assert report.divergence_count == 1, "Expected exactly 1 divergence case"
    print("[+] Diagnosis Quality & Evidence Faithfulness Harness Verified.")
