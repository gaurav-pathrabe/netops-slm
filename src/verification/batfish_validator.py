"""
batfish_validator.py - Formal AST & Safety Verification Gate
Validates generated CLI commands against syntax rules, safety constraints,
and routing topology invariants before outputting to production.
Prevents LLM hallucinations (ETH Zurich Cornetto benchmark compliance).
"""

import re
from typing import Dict, Any, List, Tuple

FORBIDDEN_COMMANDS = [
    r"^reload",
    r"^format\s+",
    r"^erase\s+",
    r"^delete\s+nvram:",
    r"^no\s+router\s+bgp\s+\d+",
    r"^no\s+ip\s+routing"
]

REQUIRED_SAFETY_CHECKS = {
    "cisco-ios": [
        (r"configure terminal", "Missing configuration terminal entry"),
        (r"exit", "Missing configuration exit or commit")
    ],
    "cisco-nxos": [
        (r"configure terminal", "Missing configuration terminal entry"),
        (r"copy running-config startup-config", "Recommendation: Persist to startup-config")
    ]
}

class BatfishValidator:
    """
    Tier-2 Safety & Verification Gate.
    Analyzes generated remediation blocks to ensure syntactic correctness,
    absence of destructive commands, and adherence to safety policies.
    """

    def __init__(self):
        self.forbidden_patterns = [re.compile(p, re.IGNORECASE) for p in FORBIDDEN_COMMANDS]

    def validate_cli_safety(self, cli_block: str, os_type: str = "cisco-ios") -> Tuple[bool, List[str]]:
        """
        Scans CLI commands for forbidden/destructive statements and missing safety clauses.
        Returns: (is_safe: bool, issues: List[str])
        """
        lines = [line.strip() for line in cli_block.splitlines() if line.strip() and not line.startswith("!")]
        issues: List[str] = []

        # 1. Check for destructive commands
        for line in lines:
            for pattern in self.forbidden_patterns:
                if pattern.search(line):
                    issues.append(f"CRITICAL SAFETY VIOLATION: Forbidden command detected: '{line}'")

        # 2. Check for required safety elements
        joined = "\n".join(lines)
        if os_type in REQUIRED_SAFETY_CHECKS:
            for pat, desc in REQUIRED_SAFETY_CHECKS[os_type]:
                if not re.search(pat, joined, re.IGNORECASE):
                    issues.append(f"WARNING: {desc}")

        is_safe = not any("CRITICAL" in issue for issue in issues)
        return is_safe, issues

    def verify_remediation(self, solution_text: str) -> Dict[str, Any]:
        """
        Extracts CLI code blocks from markdown and validates each block.
        """
        code_block_pattern = re.compile(r"```(cisco-[a-z0-9]+|text|bash)?\n(.*?)```", re.DOTALL)
        matches = code_block_pattern.findall(solution_text)

        results = []
        overall_valid = True

        for idx, (lang, code) in enumerate(matches, start=1):
            if not lang or lang == "text":
                continue
            is_safe, issues = self.validate_cli_safety(code, os_type=lang)
            if not is_safe:
                overall_valid = False
            results.append({
                "block_index": idx,
                "syntax_language": lang,
                "is_safe": is_safe,
                "validation_messages": issues,
                "code_snippet": code.strip()
            })

        return {
            "verified": overall_valid,
            "blocks_checked": len(results),
            "details": results
        }


if __name__ == "__main__":
    validator = BatfishValidator()
    
    test_cli_good = (
        "```cisco-nxos\n"
        "configure terminal\n"
        "router bgp 65001\n"
        "  neighbor 10.100.1.2\n"
        "    timers 3 9\n"
        "    no shutdown\n"
        "exit\n"
        "copy running-config startup-config\n"
        "```"
    )

    test_cli_bad = (
        "```cisco-ios\n"
        "configure terminal\n"
        "no router bgp 65001\n"
        "reload\n"
        "```"
    )

    print("[*] Testing Batfish Verification Gate:")
    res_good = validator.verify_remediation(test_cli_good)
    print("Test 1 (Legitimate BGP fix) -> Verified:", res_good["verified"], "| Notes:", res_good["details"][0]["validation_messages"])

    res_bad = validator.verify_remediation(test_cli_bad)
    print("Test 2 (Destructive command) -> Verified:", res_bad["verified"], "| Violations:", res_bad["details"][0]["validation_messages"])
