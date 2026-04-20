import pytest

import pandas as pd

from fpl.logic import (
    add_estimated_effective_ownership,
    build_captaincy_matrix,
    build_weekly_plan_markdown,
    compute_shield_attack_scores,
    get_upcoming_fixtures,
    style_ticker,
)


def test_get_upcoming_fixtures_formats_single_fixture():
    data = {"events": [{"id": 10, "is_current": True}]}
    fixtures = [
        {
            "event": 11,
            "team_h": 1,
            "team_a": 2,
            "team_h_difficulty": 2,
            "team_a_difficulty": 4,
        }
    ]
    team_map = {1: "Arsenal", 2: "Chelsea"}

    out = get_upcoming_fixtures(team_id=1, fixtures=fixtures, data=data, team_map=team_map, num_gws=1)
    assert out == ["Che (H) | 2"]


def test_get_upcoming_fixtures_formats_dgw_and_blank():
    data = {"events": [{"id": 1, "is_current": True}]}
    fixtures = [
        {"event": 2, "team_h": 1, "team_a": 2, "team_h_difficulty": 2, "team_a_difficulty": 4},
        {"event": 2, "team_h": 3, "team_a": 1, "team_h_difficulty": 3, "team_a_difficulty": 3},
        {"event": 3, "team_h": 2, "team_a": 3, "team_h_difficulty": 2, "team_a_difficulty": 2},
    ]
    team_map = {1: "Arsenal", 2: "Chelsea", 3: "Everton"}

    out = get_upcoming_fixtures(team_id=1, fixtures=fixtures, data=data, team_map=team_map, num_gws=2)
    assert out == ["DGW (2)", "BLANK"]


def test_get_upcoming_fixtures_returns_na_on_bad_data():
    out = get_upcoming_fixtures(team_id=1, fixtures=[], data={}, team_map={}, num_gws=3)
    assert out == ["N/A", "N/A", "N/A"]


@pytest.mark.parametrize(
    "val, expected_substrings",
    [
        ("DGW (2)", ["#38003c", "color: white"]),
        ("Che (H) | 1", ["#00753e", "color: white"]),
        ("Che (H) | 2", ["#01fc7a", "color: black"]),
        ("Che (H) | 3", ["#e7e7e7", "color: black"]),
        ("Che (H) | 4", ["#ff1751", "color: white"]),
        ("Che (H) | 5", ["#80072d", "color: white"]),
    ],
)
def test_style_ticker_colors(val, expected_substrings):
    css = style_ticker(val)
    for s in expected_substrings:
        assert s in css


def test_style_ticker_invalid_value_returns_empty():
    assert style_ticker(None) == ""
    assert "#f3f4f6" in style_ticker("BLANK")
    assert "#f3f4f6" in style_ticker("N/A")


def test_build_captaincy_matrix_adds_reason_codes_and_confidence():
    squad = pd.DataFrame(
        [
            {
                "id": 1,
                "web_name": "Salah",
                "form": 7.2,
                "ict_index": 120.0,
                "Diff": 2,
                "Loc": "H",
                "proj_pts": 8.5,
                "play_prob": 0.95,
                "selected_by_percent": 45.0,
                "avg_minutes": 85,
            },
            {
                "id": 2,
                "web_name": "Palmer",
                "form": 4.0,
                "ict_index": 90.0,
                "Diff": 4,
                "Loc": "A",
                "proj_pts": 5.0,
                "play_prob": 0.7,
                "selected_by_percent": 15.0,
                "avg_minutes": 60,
            },
        ]
    )
    out = build_captaincy_matrix(squad, max_ict=120.0)

    assert list(out["web_name"]) == ["Salah", "Palmer"]
    assert "Reason Codes" in out.columns
    assert "Confidence Tier" in out.columns
    assert out.iloc[0]["Confidence Tier"] == "High"
    assert "FORM+" in out.iloc[0]["Reason Codes"]
    assert out.iloc[1]["Confidence Tier"] in {"Low", "Medium"}
    assert "FIXTURE-" in out.iloc[1]["Reason Codes"]


def test_add_estimated_effective_ownership_and_scores():
    pool = pd.DataFrame(
        [
            {"id": 1, "web_name": "A", "selected_by_percent": 50, "play_prob": 1.0, "proj_pts": 6.0},
            {"id": 2, "web_name": "B", "selected_by_percent": 45, "play_prob": 1.0, "proj_pts": 6.0},
            {"id": 3, "web_name": "C", "selected_by_percent": 20, "play_prob": 1.0, "proj_pts": 5.0},
            {"id": 4, "web_name": "D", "selected_by_percent": 10, "play_prob": 1.0, "proj_pts": 4.0},
        ]
    )
    eo = add_estimated_effective_ownership(pool, captain_ids={1})
    assert float(eo.loc[eo["id"] == 1, "est_eo"].iloc[0]) == 100.0
    assert "attack_index" in eo.columns

    scores = compute_shield_attack_scores(
        eo,
        squad_player_ids={1, 4},
        top_n=3,
        differential_eo_cap=20.0,
    )
    assert 0 <= scores["shield_score"] <= 100
    assert 0 <= scores["attack_score"] <= 100
    assert scores["core_total_count"] == 3
    assert isinstance(scores["core_dangers"], pd.DataFrame)
    assert isinstance(scores["attack_assets"], pd.DataFrame)


def test_build_weekly_plan_markdown_contains_key_sections():
    md = build_weekly_plan_markdown(
        gw_id=31,
        captain={"web_name": "Saka", "Opp": "CHE"},
        vice_captain={"web_name": "Haaland", "Opp": "AVL"},
        xi_names=["A", "B", "C"],
        bench_names=["D", "E"],
        transfer_note="Sell X, buy Y",
        chip_note="Roll transfer",
        risk_notes=["Minutes risk on C", "Tough fixture for B"],
    )

    assert "GW31 Weekly Plan" in md
    assert "**Captain:** Saka (vs CHE)" in md
    assert "**Transfer idea:** Sell X, buy Y" in md
    assert "Minutes risk on C" in md

