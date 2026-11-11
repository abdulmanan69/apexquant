"""auditor.py - risk governance (VR-01..VR-04), error classification tags, and the Memory Vault.

Every rule returns {"id", "name", "status": pass|caution|fail|na, "reason"} with the numbers
that decided it, so the UI can show "Why this verdict?".
The vault is a CSV (audit_memory_vault.csv) with one row per saved audit; results are
recorded later through settle() and summarised as ROI and closing-line value (CLV).
"""
from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from . import config as cfg
from . import quant_engine as qe

EC_TAGS = {
    "EC-00": "Clean Setup",
    "EC-01": "Line Mismatch",
    "EC-02": "Injury/Steam Trap",
    "EC-03": "High Vig/Low Liquidity",
    "EC-04": "Model/Tactical Conflict",
}


# ============================================================================
# veto rules
# ============================================================================
def vr01_min_edge(max_ev: Optional[float], veto_ev: float, sniper_ev: float) -> dict:
    """VR-01 Minimum Edge Gate: max EV < veto_ev -> fail; >= sniper_ev -> pass; between -> caution."""
    base = {"id": "VR-01", "name": "Minimum Edge Gate"}
    if max_ev is None:
        return {**base, "status": "fail", "reason": "No market with both a soft and a sharp price, so no EV can be computed."}
    if max_ev < veto_ev:
        return {**base, "status": "fail", "reason": f"Best EV {max_ev:+.2f}% is below the {veto_ev:.2f}% veto floor."}
    if max_ev >= sniper_ev:
        return {**base, "status": "pass", "reason": f"Best EV {max_ev:+.2f}% is at or above the {sniper_ev:.2f}% sniper threshold."}
    return {**base, "status": "caution", "reason": f"Best EV {max_ev:+.2f}% sits between {veto_ev:.2f}% and {sniper_ev:.2f}%: small stake only."}


def vr02_steam_trap(soft_odds: Optional[float], sharp_fair_odds: Optional[float], injury_items: List[dict],
                    gap_pct: float = cfg.VR02_STEAM_GAP_PCT) -> dict:
    """VR-02 Late Injury / Steam Trap: the soft price is more than gap_pct above the sharp fair
    price AND live news reports an injury, absence or medical timeout -> fail. News without a
    price gap -> caution. No injury news -> pass."""
    base = {"id": "VR-02", "name": "Late Injury / Steam Trap"}
    n = len(injury_items)
    if soft_odds is None or sharp_fair_odds is None:
        return {**base, "status": "na" if n == 0 else "caution",
                "reason": "No price pair to compare." if n == 0 else f"{n} injury headline(s) found but no price pair to test the gap."}
    gap = (soft_odds / sharp_fair_odds - 1.0) * 100.0
    if n == 0:
        return {**base, "status": "pass", "reason": f"No injury or absence headlines in the news feed; soft price is {gap:+.1f}% vs sharp fair odds."}
    if gap > gap_pct:
        head = injury_items[0].get("title", "")[:90]
        return {**base, "status": "fail", "reason": f"Soft price {soft_odds:.2f} is {gap:+.1f}% above the sharp fair price {sharp_fair_odds:.2f} (limit {gap_pct:.0f}%) while news reports: \"{head}\"."}
    return {**base, "status": "caution", "reason": f"{n} injury headline(s) found, but the soft price is only {gap:+.1f}% above sharp fair (limit {gap_pct:.0f}%). Read the news tab before staking."}


def vr03_liquidity(sharp_vig_pct: Optional[float], soft_odds: Optional[float], max_vig: float = cfg.VR03_MAX_VIG,
                   max_soft: float = cfg.VR03_MAX_SOFT_ODDS) -> dict:
    """VR-03 Liquidity & Variance Cap: Pinnacle vig > max_vig or soft odds > max_soft -> fail."""
    base = {"id": "VR-03", "name": "Liquidity & Variance Cap"}
    if sharp_vig_pct is None and soft_odds is None:
        return {**base, "status": "na", "reason": "No sharp market to measure."}
    problems = []
    if sharp_vig_pct is not None and sharp_vig_pct > max_vig:
        problems.append(f"Pinnacle margin {sharp_vig_pct:.2f}% exceeds {max_vig:.2f}% (thin market)")
    if soft_odds is not None and soft_odds > max_soft:
        problems.append(f"soft odds {soft_odds:.2f} exceed the {max_soft:.2f} variance cap")
    if problems:
        return {**base, "status": "fail", "reason": "; ".join(problems) + "."}
    return {**base, "status": "pass",
            "reason": f"Pinnacle margin {sharp_vig_pct:.2f}% <= {max_vig:.2f}%" + (f"; soft odds {soft_odds:.2f} <= {max_soft:.2f}." if soft_odds else ".")}


def vr04_divergence(p_model: Optional[float], p_sharp: Optional[float], pick_label: str,
                    max_pp: float = cfg.VR04_MAX_DIVERGENCE_PP) -> dict:
    """VR-04 Model vs Market Divergence: |model - Pinnacle| on the Pinnacle-implied pick > max_pp points -> fail."""
    base = {"id": "VR-04", "name": "Model vs Market Divergence"}
    if p_model is None or p_sharp is None:
        return {**base, "status": "na", "reason": "Model or sharp probability missing for the market pick."}
    pp = qe.pp_divergence(p_model, p_sharp)
    if abs(pp) > max_pp:
        return {**base, "status": "fail",
                "reason": f"On {pick_label} the model says {p_model * 100:.1f}% vs Pinnacle {p_sharp * 100:.1f}% ({pp:+.1f} pp, limit {max_pp:.1f}). Model and market disagree too much to trust either."}
    return {**base, "status": "pass",
            "reason": f"On {pick_label} the model says {p_model * 100:.1f}% vs Pinnacle {p_sharp * 100:.1f}% ({pp:+.1f} pp, within {max_pp:.1f})."}


def run_rules(best: Optional[dict], sharp_pick: Optional[dict], injury_items: List[dict], mismatches: List[str],
              settings: cfg.Settings) -> dict:
    """Apply the four rules. `best` is the best-EV row (or None); `sharp_pick` the row Pinnacle favours.
    Returns rules, vetoed flag, ec_tag and the verdict tier."""
    max_ev = best["ev_pct"] if best else None
    rules = [
        vr01_min_edge(max_ev, settings.veto_ev, settings.sniper_ev),
        vr02_steam_trap(best["soft"] if best else None, best.get("sharp_fair_odds") if best else None, injury_items),
        vr03_liquidity(best.get("sharp_vig_pct") if best else None, best["soft"] if best else None,
                       settings.max_vig, settings.max_soft_odds),
        vr04_divergence(sharp_pick.get("p_model") if sharp_pick else None, sharp_pick.get("p_sharp") if sharp_pick else None,
                        sharp_pick.get("label", "the market pick") if sharp_pick else "the market pick", settings.max_divergence_pp),
    ]
    hard_fail = any(r["status"] == "fail" for r in rules[1:]) or rules[0]["status"] == "fail"
    tier = qe.verdict_tier(max_ev if max_ev is not None else -99.0, any(r["status"] == "fail" for r in rules[1:]),
                           settings.sniper_ev, settings.veto_ev)
    if rules[1]["status"] == "fail":
        ec = "EC-02"
    elif rules[2]["status"] == "fail":
        ec = "EC-03"
    elif rules[3]["status"] == "fail":
        ec = "EC-04"
    elif mismatches:
        ec = "EC-01"
    else:
        ec = "EC-00"
    return {"rules": rules, "vetoed": hard_fail, "ec_tag": ec, "ec_label": EC_TAGS[ec], "verdict": tier,
            "all_green": all(r["status"] in ("pass", "na") for r in rules)}


# ============================================================================
# Memory Vault (CSV)
# ============================================================================
COLUMNS = ["id", "timestamp", "sport", "match", "market", "selection", "soft_odds", "sharp_odds", "p_sharp", "p_model",
           "p_master", "ev_pct", "stake_pct", "verdict", "ec_tag", "closing_odds", "result", "notes"]


def _ensure(path: str = cfg.VAULT_CSV) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            csv.DictWriter(fh, fieldnames=COLUMNS).writeheader()


def read_vault(path: str = cfg.VAULT_CSV) -> List[dict]:
    _ensure(path)
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for r in rows:
        rr = dict(r)
        for k in ("soft_odds", "sharp_odds", "p_sharp", "p_model", "p_master", "ev_pct", "stake_pct", "closing_odds"):
            rr[k] = float(r[k]) if r.get(k) not in (None, "") else None
        rr["id"] = int(r["id"])
        out.append(rr)
    return out


def _write_all(rows: List[dict], path: str = cfg.VAULT_CSV) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in COLUMNS})


def append_vault(entry: dict, path: str = cfg.VAULT_CSV) -> dict:
    rows = read_vault(path)
    entry = dict(entry)
    entry["id"] = (max((r["id"] for r in rows), default=0) + 1)
    if not entry.get("timestamp"):
        entry["timestamp"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    entry.setdefault("result", None)
    entry.setdefault("closing_odds", None)
    entry.setdefault("notes", "")
    rows.append(entry)
    _write_all(rows, path)
    return entry


def settle(entry_id: int, result: Optional[str] = None, closing_odds: Optional[float] = None,
           notes: Optional[str] = None, path: str = cfg.VAULT_CSV) -> Optional[dict]:
    rows = read_vault(path)
    hit = None
    for r in rows:
        if r["id"] == entry_id:
            if result is not None:
                r["result"] = result
            if closing_odds is not None:
                r["closing_odds"] = closing_odds
            if notes is not None:
                r["notes"] = notes
            hit = r
    if hit:
        _write_all(rows, path)
    return hit


def profit_units(result: Optional[str], odds: float, stake: float) -> Optional[float]:
    """Profit in stake units for a settled result at decimal odds."""
    if not result:
        return None
    b = odds - 1.0
    return {"win": stake * b, "loss": -stake, "push": 0.0, "half-win": stake * b / 2.0, "half-loss": -stake / 2.0}.get(result)


def summary(rows: List[dict], bankroll: float) -> dict:
    """ROI on settled rows (stake = stake_pct % of bankroll at save time) and CLV on rows with a closing price.
    CLV = soft_odds / closing_odds - 1 (positive = the price beat the close)."""
    settled = [r for r in rows if r.get("result")]
    staked = sum((r["stake_pct"] or 0.0) / 100.0 * bankroll for r in settled)
    profit = sum((profit_units(r["result"], r["soft_odds"], (r["stake_pct"] or 0.0) / 100.0 * bankroll) or 0.0) for r in settled)
    clv_rows = [r for r in rows if r.get("closing_odds")]
    clvs = [r["soft_odds"] / r["closing_odds"] - 1.0 for r in clv_rows]
    by_verdict: Dict[str, dict] = {}
    for r in rows:
        v = by_verdict.setdefault(r["verdict"], {"n": 0, "settled": 0, "profit": 0.0, "staked": 0.0, "clv": []})
        v["n"] += 1
        if r.get("result"):
            st = (r["stake_pct"] or 0.0) / 100.0 * bankroll
            v["settled"] += 1
            v["staked"] += st
            v["profit"] += profit_units(r["result"], r["soft_odds"], st) or 0.0
        if r.get("closing_odds"):
            v["clv"].append(r["soft_odds"] / r["closing_odds"] - 1.0)
    for v in by_verdict.values():
        v["roi_pct"] = (v["profit"] / v["staked"] * 100.0) if v["staked"] > 0 else None
        v["mean_clv_pct"] = (sum(v["clv"]) / len(v["clv"]) * 100.0) if v["clv"] else None
        v["n_clv"] = len(v["clv"])
        del v["clv"]
    cumulative = []
    running = 0.0
    for r in settled:
        running += profit_units(r["result"], r["soft_odds"], (r["stake_pct"] or 0.0) / 100.0 * bankroll) or 0.0
        cumulative.append({"id": r["id"], "timestamp": r["timestamp"], "cum_profit": round(running, 2)})
    return {"n": len(rows), "n_settled": len(settled), "staked": round(staked, 2), "profit": round(profit, 2),
            "roi_pct": (profit / staked * 100.0) if staked > 0 else None,
            "n_clv": len(clvs), "mean_clv_pct": (sum(clvs) / len(clvs) * 100.0) if clvs else None,
            "by_verdict": by_verdict, "cumulative": cumulative, "bankroll": bankroll}
