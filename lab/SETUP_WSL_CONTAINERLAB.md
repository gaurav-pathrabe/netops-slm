# NetOps-SLM v1 — WSL2 & Containerlab Setup Guide

**Target OS:** Windows 11 (64-bit)  
**Host Hardware:** Intel Core i5-1240P, 16 GB RAM, RTX 2050 (4 GB VRAM)  
**Prerequisites:** Administrator access for initial WSL2 feature enablement.

---

## Step 1: Install WSL2 and Ubuntu (Elevated PowerShell)

Open PowerShell as **Administrator** (Right-click PowerShell -> *Run as Administrator*):

```powershell
wsl --install -d Ubuntu-24.04
```

*Note: If prompted, reboot your computer to complete the Virtual Machine Platform feature installation.*

---

## Step 2: Configure Docker Engine & Containerlab inside WSL2

Open your newly installed **Ubuntu 24.04** terminal and run:

```bash
# 1. Update and install prerequisites
sudo apt-get update && sudo apt-get install -y curl ca-certificates git python3-pip python3-venv

# 2. Install Docker Engine (Rootless / Systemd)
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# 3. Start Docker service
sudo service docker start

# 4. Install Containerlab (Official binary script)
bash -c "$(curl -sL https://get.containerlab.dev)"

# 5. Verify installations
docker --version
containerlab version
```

---

## Step 3: Run the NetOps-SLM Milestone 1 Lab

Navigate to the project directory from inside WSL2:

```bash
cd /mnt/c/Users/kali/Downloads/cmdc/NetOps_LLM_and_Jobs/lab

# 1. Deploy the pinned 2-router FRR topology + Linux endpoints
sudo containerlab deploy -t topology.clab.yml --reconfigure

# 2. Verify healthy baseline reachability
python3 scripts/verify_health.py --run_type baseline_check

# 3. Inject BGP neighbor admin shutdown
./scripts/inject_fault.sh

# 4. Verify post-fault reachability loss
python3 scripts/verify_health.py --run_type post_fault_check

# 5. Apply deterministic runbook recovery
./scripts/recover_bgp.sh

# 6. Verify full recovery and inspect logged evidence
python3 scripts/verify_health.py --run_type recovery_verification
cat ../evidence/demo_runs.jsonl
```

---

## Step 4: Run Fine-Tuning & Evaluation Harness

To train the 4-bit QLoRA adapter or run the held-out benchmark using the dedicated virtual environment:

```bash
cd /mnt/c/Users/kali/Downloads/cmdc/NetOps_LLM_and_Jobs

# 1. Activate dedicated ML virtual environment
source /opt/netops-venv/bin/activate

# 2. Run baseline comparison (Deterministic Runbook vs Base SLM)
python3 src/evaluation/run_baseline_comparison.py

# 3. (Optional) Re-train 4-bit QLoRA adapter on RTX 2050 (130 seconds)
python3 src/training/train_qwen_lora.py

# 4. Evaluate fine-tuned LoRA adapter on held-out episodes
python3 src/evaluation/evaluate_finetuned_lora.py
```

---

## Step 5: Tear Down Lab

When done testing:

```bash
cd /mnt/c/Users/kali/Downloads/cmdc/NetOps_LLM_and_Jobs/lab
sudo containerlab destroy -t topology.clab.yml --cleanup
```
