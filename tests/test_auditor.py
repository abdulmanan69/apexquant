"""Veto rules, EC tags and the CSV vault."""
import pytest

from backend import auditor, config as cfg


def test_vr01_tiers():
    assert auditor.vr01_min_edge(None, 0.5, 1.2)["status"] == "fail"
    assert auditor.vr01_min_edge(0.49, 0.5, 1.2)["status"] == "fail"
    assert auditor.vr01_min_edge(0.80, 0.5, 1.2)["status"] == "caution"
    assert auditor.vr01_min_edge(1.20, 0.5, 1.2)["status"] == "pass"


def test_vr02_steam_trap():
    inj = [{"title": "Star striker ruled out"}]
    assert auditor.vr02_steam_trap(2.20, 2.00, inj)["status"] == "fail"       # +10% above fair and injury news
    assert auditor.vr02_steam_trap(2.05, 2.00, inj)["status"] == "caution"    # +2.5% only
    assert auditor.vr02_steam_trap(2.20, 2.00, [])["status"] == "pass"
    assert auditor.vr02_steam_trap(None, None, [])["status"] == "na"


def test_vr03_liquidity():
    assert auditor.vr03_liquidity(2.5, 3.0)["status"] == "pass"
    assert auditor.vr03_liquidity(5.0, 3.0)["status"] == "fail"
    assert auditor.vr03_liquidity(2.5, 4.6)["status"] == "fail"
    assert auditor.vr03_liquidity(None, None)["status"] == "na"


def test_vr04_divergence():
    assert auditor.vr04_divergence(0.55, 0.50, "Home")["status"] == "pass"
    assert auditor.vr04_divergence(0.60, 0.50, "Home")["status"] == "fail"    # 10 pp


def test_run_rules_tags_and_verdict():
    s = cfg.Settings()
    best = {"ev_pct": 1.5, "soft": 2.0, "sharp_fair_odds": 1.95, "sharp_vig_pct": 2.0}
    pick = {"p_model": 0.52, "p_sharp": 0.51, "label": "Home"}
    out = auditor.run_rules(best, pick, [], [], s)
    assert out["verdict"] == "SNIPER" and out["ec_tag"] == "EC-00" and out["all_green"]
    out = auditor.run_rules(best, pick, [], ["Line mismatch"], s)
    assert out["ec_tag"] == "EC-01" and out["verdict"] == "SNIPER"
    out = auditor.run_rules({**best, "sharp_vig_pct": 6.0}, pick, [], [], s)
    assert out["verdict"] == "VETO" and out["ec_tag"] == "EC-03"
    out = auditor.run_rules(best, {**pick, "p_model": 0.70}, [], [], s)
    assert out["verdict"] == "VETO" and out["ec_tag"] == "EC-04"
    out = auditor.run_rules({**best, "soft": 2.3}, pick, [{"title": "injury"}], [], s)
    assert out["verdict"] == "VETO" and out["ec_tag"] == "EC-02"
    out = auditor.run_rules({**best, "ev_pct": 0.8}, pick, [], [], s)
    assert out["verdict"] == "CAUTION"
    assert auditor.run_rules(None, None, [], [], s)["verdict"] == "VETO"


def test_vault_roundtrip(tmp_path):
    path = str(tmp_path / "vault.csv")
    e = auditor.append_vault({"sport": "football", "match": "A vs B", "market": "1X2", "selection": "A win", "soft_odds": 2.0,
                              "sharp_odds": 1.9, "p_sharp": 0.52, "p_model": 0.55, "p_master": 0.53, "ev_pct": 6.0,
                              "stake_pct": 2.0, "verdict": "SNIPER", "ec_tag": "EC-00"}, path)
    assert e["id"] == 1
    e2 = auditor.append_vault({**e, "selection": "B win", "verdict": "CAUTION", "stake_pct": 0.5}, path)
    assert e2["id"] == 2
    assert auditor.settle(1, "win", 1.9, "closed shorter", path)["result"] == "win"
    assert auditor.settle(2, "loss", None, None, path)["result"] == "loss"
    assert auditor.settle(99, "win", None, None, path) is None
    rows = auditor.read_vault(path)
    s = auditor.summary(rows, 1000.0)
    # row1: stake 20 at 2.0 win -> +20 ; row2: stake 5 loss -> -5 ; staked 25 ; ROI 60%
    assert s["n_settled"] == 2 and s["profit"] == pytest.approx(15.0) and s["staked"] == pytest.approx(25.0)
    assert s["roi_pct"] == pytest.approx(60.0)
    assert s["n_clv"] == 1 and s["mean_clv_pct"] == pytest.approx((2.0 / 1.9 - 1) * 100)
    assert s["by_verdict"]["SNIPER"]["roi_pct"] == pytest.approx(100.0)


def test_profit_units():
    assert auditor.profit_units("half-win", 2.0, 10) == 5.0
    assert auditor.profit_units("half-loss", 2.0, 10) == -5.0
    assert auditor.profit_units("push", 2.0, 10) == 0.0
    assert auditor.profit_units(None, 2.0, 10) is None
