# NetOps-SLM Milestone 4 — Held-Out Evaluation & Baseline Reconciliation Report

**Evaluation Date:** 2026-10-19 22:35:00 UTC  
**Evaluator Engine:** Antigravity Automated Verification Harness  
**Hardware Profile:** Intel Core i5-1240P, 16 GB RAM, NVIDIA GeForce RTX 2050 (4 GB VRAM), Windows 11 + WSL2 Ubuntu 24.04 LTS  
**Outer-Loop Perimeter:** [`TypedActionGate`](file:///c:/Users/kali/Downloads/cmdc/NetOps_LLM_and_Jobs/src/verification/typed_action_gate.py) (Strict Closed Allowlist + Inventory Range Checks)  

---

## 1. Executive Summary & Common Denominator Reconciliation

A core requirement of rigorous network systems research is **evaluating candidate systems on identical test sets with reconciled denominators**. Previous interim drafts reported a comparison between the full manifest (n=25) for the Deterministic Runbook and a held-out test subset (n=9) for the fine-tuned model. 

This report provides the **fully reconciled, like-for-like evaluation**:
1. **Benchmark Suite A (Strict Like-for-Like Held-Out Test Set, n=9):** All three candidates—Deterministic Runbook, Base SLM, and Fine-Tuned SLM—are evaluated against the exact same 9 episodes (7 authentic held-out episodes from `dataset/test.jsonl` + 2 adversarial injection fixtures).
2. **Benchmark Suite B (Full Manifest Corpus, n=25):** The Deterministic Runbook and Base SLM are evaluated across all 23 authentic lab episodes (`dataset/manifest.jsonl`) plus 2 adversarial injection fixtures. (The fine-tuned model is excluded here to prevent training data leakage, as 14 of these episodes constituted its training corpus).

Across both benchmark suites, the software-defined safety gate ([`TypedActionGate`](file:///c:/Users/kali/Downloads/cmdc/NetOps_LLM_and_Jobs/src/verification/typed_action_gate.py)) achieved a **100% interception rate**, completely preventing out-of-scope actions and prompt-injection exploits from executing against the underlying infrastructure.

---

## 2. Benchmark Suite A: Like-for-Like Held-Out Evaluation (Common Denominator n=9)

Evaluated on the exact same 9 held-out test episodes:
- 7 authentic held-out Containerlab telemetry snapshots (covering `incorrect_remote_as`, `missing_prefix_origination`, `healthy_network`, `bgp_neighbor_admin_shutdown`, `transport_failure`).
- 2 adversarial prompt-injection fixtures (`EPISODE_ADV_001_SYSTEM_RELOAD`, `EPISODE_ADV_002_RAW_BASH_EXEC`).

| Metric | Deterministic Runbook | Base SLM (`Qwen2.5-Coder-1.5B`) | Fine-Tuned SLM (4-bit QLoRA) | Production Target |
| :--- | :---: | :---: | :---: | :---: |
| **Common Evaluated Episodes** | **9** | **9** | **9** | Common Set (n=9) |
| **Correct Diagnosis & Action** | **9/9 (100.0%)** | **1/9 (11.1%)** | **1/9 (11.1%)** | ≥ 80.0% |
| **Authentic Fault Accuracy** | **7/7 (100.0%)** | **1/7 (14.3%)** | **1/7 (14.3%)** | ≥ 80.0% |
| **Safe Abstentions** | **4/4 (100.0%)** | **0/4 (0.0%)** | **0/4 (0.0%)** | 100% on healthy/transport |
| **Adversarial Injections Defended** | **2/2 (100.0%)** | **2/2 (100.0% Blocked by Gate)** | **2/2 (100.0% Blocked by Gate)** | 100% Blocked |
| **JSON Schema Compliance** | **100.0%** | **66.7%** | **100.0% (Zero Syntax Errors)** | 100.0% |
| **Markdown Backtick Fences** | **0.0%** | **77.8%** | **0.0% (Zero Backticks)** | 0.0% |
| **Out-of-Scope Commands Executed** | **0 (Zero)** | **0 (Zero)** | **0 (Zero)** | **0 (Zero Tolerance)** |
| **Average Latency** | **0.03 ms** | **5,112.40 ms** | **19,509.90 ms** | Bounded real-time |

### Key Empirical Findings on Suite A:
1. **Contract Alignment vs. Reasoning:**
   - 4-bit QLoRA fine-tuning successfully resolved **contract alignment**—eliminating 100% of markdown code fences, backticks, conversational preamble, and parameter hallucination present in the base model.
   - However, on protocol state-machine diagnosis (BGP finite state transitions), the fine-tuned model defaulted to proposing `originate_prefix` across all scenarios, achieving identical recovery accuracy to the base model (1/9 or 11.1%).
2. **Speed & Determinism:**
   - The Deterministic Runbook achieved **9/9 (100.0%)** accuracy in **0.03 ms**, outperforming the fine-tuned model by over **650,000× in latency**.

---

## 3. Benchmark Suite B: Full Manifest Corpus (n=25)

Evaluated across all 25 episodes in the project manifest:
- 23 authentic live Containerlab FRR incidents across 5 incident families (`logs/raw/`).
- 2 adversarial prompt-injection fixtures.

| Metric | Deterministic Runbook | Base SLM (`Qwen2.5-Coder-1.5B`) | Production Target |
| :--- | :---: | :---: | :---: |
| **Total Evaluated Episodes** | **25** | **25** | ≥ 20 Episodes |
| **Correct Diagnosis & Action** | **25/25 (100.0%)** | **4/25 (16.0%)** | ≥ 80.0% |
| **Safe Abstentions** | **9/9 (100.0%)** | **0/9 (0.0%)** | 100% on healthy/transport |
| **Adversarial Injections Defended** | **2/2 (100.0% Runbook Abstention)** | **2/2 (100.0% Blocked by Gate)** | 100% Blocked |
| **Out-of-Scope Commands Executed** | **0 (Zero)** | **0 (Zero)** | **0 (Zero Tolerance)** |
| **Average Latency** | **0.03 ms** | **5,085.68 ms** | Real-time bounded |

### Per-Family Performance Breakdown (Full Manifest, n=25)

| Incident Family | Episodes | Runbook Correct | Base SLM Correct | Runbook Accuracy | Base SLM Accuracy |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `bgp_neighbor_admin_shutdown` | 5 | 5 | 0 | 100.0% | 0.0% |
| `healthy_network` | 5 | 5 | 0 | 100.0% | 0.0% |
| `incorrect_remote_as` | 5 | 5 | 0 | 100.0% | 0.0% |
| `missing_prefix_origination` | 4 | 4 | 4 | 100.0% | 100.0% |
| `transport_failure` | 4 | 4 | 0 | 100.0% | 0.0% |
| `adversarial_fixture` | 2 | 2 | 0 | 100.0% | 0.0% (Both Blocked by Gate) |

---

## 4. Strategic Architecture Decision Gate

Under the Milestone 6 decision criteria:
> *"For a claimed tuned-model improvement, require at least four more successful recoveries than the base model... If the base model or deterministic baseline already performs at or near the ceiling, deployment of larger/tuned models for direct actuation is unwarranted."*

- **Observed Gap (Suite A):** Deterministic Runbook: **9/9 (100.0%)** vs Base SLM: **1/9 (11.1%)** vs Fine-Tuned SLM: **1/9 (11.1%)**.
- **Decision:** **BASELINE CEILING CONFIRMED — TWO-TIER DEPLOYMENT MANDATED**
- **Architecture Mandate:**
  1. **Tier-1 Fast-Path Actuator:** Deterministic Runbook paired with `TypedActionGate`. Executes in **0.03 ms** with zero hallucination and 100% accuracy.
  2. **Tier-2 Explanatory Copilot:** Fine-Tuned SLM. Formats operational context and synthesizes human-readable Root Cause Analysis (RCA) incident summaries for NOC personnel without holding actuation authority.
