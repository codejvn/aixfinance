"""
policy.py — Trading Policy Rulebook

policy.json acts as a per-sector "speed limit" file. The Actor agents read it
before proposing trades (hard constraints), and the Critic updates it after each
backtest (RLAIF feedback loop). This prevents the bot from repeating the same
high-leverage mistakes in sectors it has already burned itself on.

Lifecycle:
  1. load_policy()            — read current limits from policy.json
  2. get_sector_rules(theme)  — find the relevant sector limits for this run
  3. format_rules_for_prompt  — inject limits into LLM prompts as hard constraints
  4. update_sector(...)       — write new limits back after backtest grading
"""

import json
from pathlib import Path
from datetime import datetime, timezone

POLICY_PATH = Path(__file__).parent / "policy.json"

# ── Default policy (written on first run if policy.json doesn't exist) ────────
_DEFAULT_POLICY = {
    "version": 1,
    "last_updated": "",
    "sectors": {
        "AI": {
            "max_leverage": 4.0,
            "max_allocation_pct": 40.0,
            "notes": "High-growth tech sector. Initial default.",
            "updated_reason": "Initial default",
        },
        "Layer-1s": {
            "max_leverage": 3.0,
            "max_allocation_pct": 45.0,
            "notes": "Crypto L1 tokens — high volatility. Initial default.",
            "updated_reason": "Initial default",
        },
        "DeFi": {
            "max_leverage": 2.0,
            "max_allocation_pct": 30.0,
            "notes": "DeFi protocols — extreme volatility, low liquidity. Initial default.",
            "updated_reason": "Initial default",
        },
        "RWAs": {
            "max_leverage": 2.0,
            "max_allocation_pct": 35.0,
            "notes": "Real World Assets — illiquid, regulatory risk. Initial default.",
            "updated_reason": "Initial default",
        },
        "Geopolitics": {
            "max_leverage": 3.0,
            "max_allocation_pct": 40.0,
            "notes": "Defense & macro — event-driven volatility spikes. Initial default.",
            "updated_reason": "Initial default",
        },
        "Energy": {
            "max_leverage": 3.0,
            "max_allocation_pct": 40.0,
            "notes": "Energy sector — macro-correlated, commodity risk. Initial default.",
            "updated_reason": "Initial default",
        },
        "Biotech": {
            "max_leverage": 2.0,
            "max_allocation_pct": 30.0,
            "notes": "Biotech — binary catalyst risk (FDA, trials). Initial default.",
            "updated_reason": "Initial default",
        },
    },
    "global": {
        "max_leverage": 5.0,
        "max_allocation_pct": 50.0,
        "notes": "Fallback limits for themes not matched to a specific sector.",
    },
}


# ── I/O ───────────────────────────────────────────────────────────────────────

def load_policy() -> dict:
    """Load policy.json. Creates it with defaults if it doesn't exist yet."""
    if not POLICY_PATH.exists():
        print(f"[Policy] policy.json not found — initialising with defaults.")
        _write_policy(_DEFAULT_POLICY)
        return _DEFAULT_POLICY

    with open(POLICY_PATH, "r") as f:
        policy = json.load(f)

    print(
        f"[Policy] Loaded policy.json "
        f"(v{policy.get('version', '?')}, "
        f"updated {policy.get('last_updated', '?')[:10]})"
    )
    return policy


def _write_policy(policy: dict) -> None:
    policy["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(POLICY_PATH, "w") as f:
        json.dump(policy, f, indent=2)
    print(f"[Policy] policy.json written.")


# ── Sector lookup ─────────────────────────────────────────────────────────────

def get_sector_rules(theme: str, policy: dict) -> dict:
    """
    Find the best-matching sector for a theme and return its rules,
    merged with global defaults as a floor.

    Returns a flat dict with keys:
        max_leverage, max_allocation_pct, notes, _sector_key
    """
    sectors    = policy.get("sectors", {})
    theme_low  = theme.lower()

    for key, rules in sectors.items():
        if key.lower() in theme_low or theme_low in key.lower():
            merged = {**policy.get("global", {}), **rules, "_sector_key": key}
            print(
                f"[Policy] '{theme}' → sector '{key}' | "
                f"max_leverage={merged['max_leverage']}x, "
                f"max_allocation={merged['max_allocation_pct']}%"
            )
            return merged

    # No sector match — fall back to global
    fallback = {**policy.get("global", {}), "_sector_key": None}
    print(
        f"[Policy] '{theme}' → no sector match, using global defaults | "
        f"max_leverage={fallback.get('max_leverage')}x"
    )
    return fallback


def format_rules_for_prompt(rules: dict) -> str:
    """
    Format sector rules as a hard-constraint block to prepend to LLM prompts.
    Uses forceful language so the model treats these as non-negotiable limits.
    """
    sector_label = rules.get("_sector_key") or "Global"
    return (
        f"═══ POLICY CONSTRAINTS [{sector_label}] — HARD LIMITS ═══\n"
        f"You are PROHIBITED from proposing trades that exceed these limits.\n"
        f"  Max leverage per position : {rules.get('max_leverage', 5.0)}x\n"
        f"  Max allocation per position: {rules.get('max_allocation_pct', 50.0)}%\n"
        f"  Policy note: {rules.get('notes', '')}\n"
        f"═══════════════════════════════════════════════════\n"
    )


# ── Policy update (called after backtest grading) ─────────────────────────────

def update_sector(
    theme: str,
    new_rules: dict,
    policy: dict,
) -> dict:
    """
    Write updated sector rules back to policy.json.

    Args:
        theme:     the theme string used to match the sector
        new_rules: dict with at least max_leverage, max_allocation_pct, notes,
                   updated_reason (typically returned by agents.update_policy_from_backtest)
        policy:    the currently loaded policy dict (will be mutated and written)

    Returns:
        dict with keys: sector_key, old_rules, new_rules (for display in app.py)
    """
    sector_key = new_rules.pop("_sector_key", None)

    # If no sector was matched, store under the theme name itself
    if sector_key is None:
        sector_key = theme

    old_rules = policy.get("sectors", {}).get(sector_key, {}).copy()

    if "sectors" not in policy:
        policy["sectors"] = {}

    policy["sectors"][sector_key] = {
        "max_leverage":      new_rules.get("max_leverage", old_rules.get("max_leverage", 3.0)),
        "max_allocation_pct": new_rules.get("max_allocation_pct", old_rules.get("max_allocation_pct", 40.0)),
        "notes":             new_rules.get("notes", ""),
        "updated_reason":    new_rules.get("updated_reason", ""),
    }

    _write_policy(policy)
    print(
        f"[Policy] '{sector_key}' updated: "
        f"leverage {old_rules.get('max_leverage', '?')}x → "
        f"{policy['sectors'][sector_key]['max_leverage']}x | "
        f"reason: {new_rules.get('updated_reason', '')}"
    )

    return {
        "sector_key": sector_key,
        "old_rules":  old_rules,
        "new_rules":  policy["sectors"][sector_key],
    }
