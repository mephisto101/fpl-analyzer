import pytest

from fpl.logic import get_upcoming_fixtures, style_ticker


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

