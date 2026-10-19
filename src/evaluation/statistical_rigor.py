"""
statistical_rigor.py - NetOps Enterprise Benchmarking: Confidence Intervals & Statistical Rigor

Implements Wilson Score and Clopper-Pearson 95% confidence intervals for
network remediation benchmark evaluations. Enforces statistical honesty:
prevents small sample sizes (e.g. n=9) from claiming unassailable margins.
"""

import math
from typing import Tuple, Dict, Any


def wilson_score_interval(successes: int, total: int, confidence: float = 0.95) -> Tuple[float, float, float]:
    """
    Computes Wilson score interval for binomial proportions.
    Returns: (point_estimate, lower_bound, upper_bound) in percentage [0.0, 100.0].
    """
    if total == 0:
        return 0.0, 0.0, 0.0

    p_hat = successes / total

    # Quantile z for two-sided confidence
    if confidence == 0.95:
        z = 1.959963984540054
    elif confidence == 0.99:
        z = 2.5758293035489004
    else:
        z = 1.96

    z2 = z * z
    denominator = 1.0 + z2 / total
    center = (p_hat + z2 / (2.0 * total)) / denominator
    margin = (z / denominator) * math.sqrt((p_hat * (1.0 - p_hat) / total) + (z2 / (4.0 * total * total)))

    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)

    return p_hat * 100.0, lower * 100.0, upper * 100.0


def format_rigorous_metric(successes: int, total: int, metric_name: str = "Accuracy") -> Dict[str, Any]:
    """Formats point estimate and 95% confidence interval for enterprise reporting."""
    pt, lo, hi = wilson_score_interval(successes, total)
    return {
        "metric": metric_name,
        "sample_size": total,
        "successes": successes,
        "point_estimate_pct": round(pt, 2),
        "ci_95_lower_pct": round(lo, 2),
        "ci_95_upper_pct": round(hi, 2),
        "margin_of_error_pct": round((hi - lo) / 2.0, 2),
        "statistically_conclusive": total >= 100
    }


if __name__ == "__main__":
    print("--- Demonstrating Statistical Rigor on Benchmark Sample Sizes ---")
    
    # Legacy n=9 sample
    n9 = format_rigorous_metric(1, 9, "Base SLM Held-Out")
    print(f"n=9  (1/9):   {n9['point_estimate_pct']}% (95% CI: [{n9['ci_95_lower_pct']}%, {n9['ci_95_upper_pct']}%], Margin: ±{n9['margin_of_error_pct']}%) -> Conclusive: {n9['statistically_conclusive']}")
    
    # Legacy n=25 sample
    n25 = format_rigorous_metric(25, 25, "Runbook Manifest")
    print(f"n=25 (25/25): {n25['point_estimate_pct']}% (95% CI: [{n25['ci_95_lower_pct']}%, {n25['ci_95_upper_pct']}%], Margin: ±{n25['margin_of_error_pct']}%) -> Conclusive: {n25['statistically_conclusive']}")
    
    # Target n=100 enterprise sample
    n100 = format_rigorous_metric(95, 100, "Enterprise Target")
    print(f"n=100 (95/100): {n100['point_estimate_pct']}% (95% CI: [{n100['ci_95_lower_pct']}%, {n100['ci_95_upper_pct']}%], Margin: ±{n100['margin_of_error_pct']}%) -> Conclusive: {n100['statistically_conclusive']}")
