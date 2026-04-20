import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as go
import json
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import io
import zipfile

from fpl.logic import (
    build_one_click_plan_markdown,
    captain_confidence,
    captain_reason_breakdown,
    eo_risk_panel,
    why_not_notes,
)

# ==========================================
# 1. PAGE CONFIGURATION & CSS
# ==========================================
st.set_page_config(page_title="FPL Elite Dashboard", layout="wide")

st.markdown("""
    <style>
    /* =========================
       Main content (light)
       ========================= */
    [data-testid="stMetricLabel"] div, [data-testid="stMetricLabel"] p {
        color: #111827 !important;
        font-weight: 700 !important;
    }
    .stMarkdown h3 { color: #111827 !important; }
    [data-testid="stMetricValue"] div { color: #000000 !important; }
    [data-testid="stMetric"] {
        background-color: #ffffff !important;
        border: 1px solid #e2e8f0 !important;
        border-radius: 10px !important;
        padding: 10px !important;
    }

    /* =========================
       Sidebar (high contrast)
       ========================= */
    section[data-testid="stSidebar"] {
        background: #0b1220 !important;
    }
    /* Wider sidebar on desktop only (mobile must stay fluid).
       Important: only apply when sidebar is EXPANDED, otherwise it breaks collapse reflow. */
    @media (min-width: 1100px) {
        section[data-testid="stSidebar"][aria-expanded="true"],
        section[data-testid="stSidebar"][aria-expanded="true"] > div {
            width: 26rem !important;
            min-width: 26rem !important;
        }
    }
    section[data-testid="stSidebar"] * {
        color: #e5e7eb;
    }
    section[data-testid="stSidebar"] a {
        color: #93c5fd !important;
    }

    /* Make sidebar tiles readable */
    section[data-testid="stSidebar"] [data-testid="stMetric"] {
        background: #111827 !important;
        border: 1px solid rgba(255,255,255,0.12) !important;
        border-radius: 12px !important;
        padding: 12px !important;
    }
    section[data-testid="stSidebar"] [data-testid="stMetricLabel"] div,
    section[data-testid="stSidebar"] [data-testid="stMetricLabel"] p {
        color: #e5e7eb !important;
        font-weight: 700 !important;
        letter-spacing: 0.2px;
        font-size: 0.85rem !important;
        white-space: normal !important;
        line-height: 1.15 !important;
    }
    section[data-testid="stSidebar"] [data-testid="stMetricValue"] div {
        color: #ffffff !important;
        font-weight: 800 !important;
        font-size: 1.6rem !important;
        white-space: normal !important;
        overflow: visible !important;
        text-overflow: clip !important;
        line-height: 1.15 !important;
    }
    section[data-testid="stSidebar"] [data-testid="stMetricDelta"] {
        opacity: 0.95;
    }

    /* Improve spacing for cramped sidebar layouts */
    section[data-testid="stSidebar"] .block-container {
        padding-top: 1.25rem !important;
        padding-bottom: 1.25rem !important;
    }

    /* =========================
       Mobile responsiveness
       ========================= */
    @media (max-width: 768px) {
        /* Stack Streamlit columns vertically */
        div[data-testid="stHorizontalBlock"] {
            flex-wrap: wrap !important;
        }
        div[data-testid="stHorizontalBlock"] > div {
            width: 100% !important;
            flex: 1 1 100% !important;
            min-width: 100% !important;
        }

        /* Reduce padding and type scale */
        .block-container {
            padding-left: 0.9rem !important;
            padding-right: 0.9rem !important;
        }
        section[data-testid="stSidebar"] .block-container {
            padding-left: 0.9rem !important;
            padding-right: 0.9rem !important;
        }
        section[data-testid="stSidebar"] [data-testid="stMetricValue"] div {
            font-size: 1.35rem !important;
        }

        /* Make dataframes usable on small screens */
        div[data-testid="stDataFrame"] {
            overflow-x: auto !important;
        }
    }
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 2. CONSTANTS
# ==========================================
FPL_BASE_URL = "https://fantasy.premierleague.com/api/"
REQUEST_TIMEOUT = 10


def _build_http_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


_HTTP = _build_http_session()


def _fetch_json(url: str):
    resp = _HTTP.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()

DIFF_COLORS = {1: '#00753e', 2: '#01fc7a', 3: '#e7e7e7', 4: '#ff1751', 5: '#80072d'}
DIFF_LIGHT_TEXT = {3}

FORM_TC_THRESHOLD = 5.0
BLANK_FREE_HIT_THRESHOLD = 4
DGW_BENCH_BOOST_THRESHOLD = 3
TRANSFER_BUDGET_BUFFER = 0.5
TRANSFER_TARGET_COUNT = 8
RADAR_METRICS = ['form', 'expected_goals', 'ict_index', 'total_points']
SQUAD_COMPOSITION = {'GKP': 2, 'DEF': 5, 'MID': 5, 'FWD': 3}
TOTAL_BUDGET = 100.0
HOME_CAPTAIN_BONUS = 0.5
DIFF_MAX_OWNERSHIP = 10.0   # below this % = differential

# All FPL chips and their display names
ALL_CHIPS = {
    'wildcard': 'Wildcard',
    'freehit': 'Free Hit',
    'bboost': 'Bench Boost',
    '3xc': 'Triple Captain',
}

COLUMN_LABELS = {
    "web_name": "Player", "team_name": "Team", "pos": "Pos", "price": "£m",
    "total_points": "Total Points", "form": "Form", "ict_index": "ICT Index",
    "expected_goals": "xG", "expected_assists": "xA",
    "expected_goal_involvements": "xGI",
    "expected_goals_conceded": "xGC",
    "efficiency": "Efficiency Score",
    "selected_by_percent": "Ownership %", "cost_change_event": "Price Change (GW)",
    "cost_change_start": "Price Change (Season)",
    "chance_of_playing_next_round": "Availability %", "news": "News",
    "next_3_fixtures": "Next 3 Fixtures", "xpts": "xPts",
    "live_pts": "Live Points", "live_bonus": "Bonus",
    "live_minutes": "Minutes", "diff_score": "Differential Score",
    "ppm": "Points per £m", "net_transfers": "Net Transfers (GW)",
    "avg_minutes": "Avg Minutes", "form_trend": "Form Trend",
    "cs_prob": "Clean Sheet %", "rotation_risk": "Rotation Risk",
    "season_ppg": "Season Pts / GW",
    "play_prob": "Play Probability",
    "proj_pts": "Projected Points",
    "set_pieces": "Set Pieces",
    "pens": "Penalties",
    "threat_score": "Threat Score",
    "in_squad": "In Squad",
    "confidence_tier": "Confidence Tier",
    "confidence_flags": "Uncertainty Flags",
}

LOCAL_SETTINGS_PATH = ".local_settings.json"


def load_local_settings(path: str = LOCAL_SETTINGS_PATH) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_local_settings(settings: dict, path: str = LOCAL_SETTINGS_PATH) -> None:
    p = Path(path)
    try:
        p.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except Exception:
        return

# ==========================================
# 3. DATA FETCHING
# ==========================================
@st.cache_data(ttl=3600)
def get_fpl_data():
    bootstrap = _fetch_json(f"{FPL_BASE_URL}bootstrap-static/")
    fixtures = _fetch_json(f"{FPL_BASE_URL}fixtures/")
    return bootstrap, fixtures

@st.cache_data(ttl=3600)
def get_manager_history(manager_id):
    return _fetch_json(f"{FPL_BASE_URL}entry/{manager_id}/history/")

@st.cache_data(ttl=300)
def get_manager_entry(manager_id):
    return _fetch_json(f"{FPL_BASE_URL}entry/{manager_id}/")

@st.cache_data(ttl=300)
def get_transfer_history(manager_id):
    return _fetch_json(f"{FPL_BASE_URL}entry/{manager_id}/transfers/")

@st.cache_data(ttl=300)
def get_league_standings(league_id):
    return _fetch_json(f"{FPL_BASE_URL}leagues-classic/{league_id}/standings/")

@st.cache_data(ttl=300)
def get_h2h_standings(league_id):
    return _fetch_json(f"{FPL_BASE_URL}leagues-h2h/{league_id}/standings/")

@st.cache_data(ttl=3600)
def get_player_history(player_id):
    return _fetch_json(f"{FPL_BASE_URL}element-summary/{player_id}/")

@st.cache_data(ttl=60)
def get_live_gw_data(gw_id):
    """Live player stats for an active gameweek. Short 60s TTL."""
    return _fetch_json(f"{FPL_BASE_URL}event/{gw_id}/live/")

try:
    data, fixtures_raw = get_fpl_data()
except requests.RequestException as e:
    st.error(f"Failed to load FPL data: {e}")
    st.stop()

players = pd.DataFrame(data['elements'])
teams = pd.DataFrame(data['teams'])
team_map = dict(zip(teams['id'], teams['name']))
team_short_map = dict(zip(teams['id'], teams.get('short_name', teams['name'])))
pos_map = dict(zip(
    [t['id'] for t in data['element_types']],
    [t['singular_name_short'] for t in data['element_types']],
))
gw_averages = {e['id']: e.get('average_entry_score', 0) for e in data['events']}

# ==========================================
# 4. DATA CLEANING
# ==========================================
players['team_name'] = players['team'].map(team_map)
players['pos'] = players['element_type'].map(pos_map)
players['price'] = players['now_cost'] / 10
numeric_cols = [
    'expected_goals', 'expected_assists', 'expected_goal_involvements', 'expected_goals_conceded',
    'ict_index', 'form',
    'total_points', 'minutes', 'selected_by_percent',
    'cost_change_event', 'cost_change_start',
    'threat', 'creativity', 'influence',
    'transfers_in_event', 'transfers_out_event',
]
for col in numeric_cols:
    if col in players.columns:
        players[col] = pd.to_numeric(players[col], errors='coerce').fillna(0)

if 'chance_of_playing_next_round' in players.columns:
    players['chance_of_playing_next_round'] = pd.to_numeric(
        players['chance_of_playing_next_round'], errors='coerce'
    ).fillna(100)

# ==========================================
# 5. PRE-COMPUTATION: xPts & next fixture diff
# ==========================================
curr_gw_event = next((e for e in data['events'] if e['is_current']), None)
next_gw = next((e for e in data['events'] if e['is_next']), None)
curr_gw_id = curr_gw_event['id'] if curr_gw_event else None
next_gw_id = (curr_gw_id + 1) if curr_gw_id else None

# Build next-GW difficulty per team
_team_next_diff = {}
if next_gw_id:
    for f in fixtures_raw:
        if f['event'] == next_gw_id:
            _team_next_diff[f['team_h']] = f['team_h_difficulty']
            _team_next_diff[f['team_a']] = f['team_a_difficulty']

# xPts: form × (6 − next_diff) / 5  (blank/missing → diff=3)
players['next_diff'] = players['team'].map(_team_next_diff).fillna(3)
players['xpts'] = (players['form'] * (6 - players['next_diff']) / 5).round(1)

# Differential score: ICT weighted by inverse of ownership (high score = hidden gem)
players['diff_score'] = (
    players['ict_index'] / players['selected_by_percent'].clip(lower=0.1)
).round(1)

# Points per million
players['ppm'] = (players['total_points'] / players['price'].clip(lower=0.1)).round(1)

# Net transfers this GW
if 'transfers_in_event' in players.columns and 'transfers_out_event' in players.columns:
    players['net_transfers'] = (
        players['transfers_in_event'] - players['transfers_out_event']
    ).astype(int)

# Average minutes per GW and rotation risk flag
_games_played = max(curr_gw_id or 1, 1)
players['avg_minutes'] = (players['minutes'] / _games_played).round(0).astype(int)
players['rotation_risk'] = players['avg_minutes'].apply(lambda m: 'Low mins' if m < 55 else '')

# Season points-per-game and form trend (positive = in form vs season average)
players['season_ppg'] = (players['total_points'] / _games_played).round(1)
players['form_trend'] = (players['form'] - players['season_ppg']).round(1)

# Clean sheet probability estimate for DEF/GKP (rough: harder fixture = less likely CS)
players['cs_prob'] = players['next_diff'].apply(
    lambda d: f"{max(0, round((6 - d) / 10 * 100))}%"
)

# ==========================================
# 6. HELPER FUNCTIONS
# ==========================================
def get_upcoming_fixtures(team_id, fixtures, data, num_gws=5):
    upcoming = []
    try:
        curr_gw = next((e['id'] for e in data['events'] if e['is_current']), None)
        if curr_gw is None:
            return upcoming
        for gw in range(curr_gw + 1, curr_gw + num_gws + 1):
            f_list = [f for f in fixtures if f['event'] == gw and (f['team_h'] == team_id or f['team_a'] == team_id)]
            if len(f_list) > 1:
                upcoming.append(f"DGW ({len(f_list)})")
            elif len(f_list) == 1:
                f = f_list[0]
                is_home = f['team_h'] == team_id
                opp = team_map[f['team_a'] if is_home else f['team_h']]
                diff = f['team_h_difficulty'] if is_home else f['team_a_difficulty']
                upcoming.append(f"{opp[:3]} ({'H' if is_home else 'A'}) | {diff}")
            else:
                upcoming.append("BLANK")
    except (KeyError, StopIteration):
        pass
    return upcoming

def get_short_fixture_run(team_id, fixtures, data, num_gws=3):
    parts = []
    curr_gw = next((e['id'] for e in data['events'] if e['is_current']), None)
    if curr_gw is None:
        return 'N/A'
    for gw in range(curr_gw + 1, curr_gw + num_gws + 1):
        f_list = [f for f in fixtures if f['event'] == gw and (f['team_h'] == team_id or f['team_a'] == team_id)]
        if not f_list:
            parts.append('BLK')
        elif len(f_list) > 1:
            parts.append('DGW')
        else:
            f = f_list[0]
            is_home = f['team_h'] == team_id
            diff = f['team_h_difficulty'] if is_home else f['team_a_difficulty']
            parts.append(str(diff))
    return '|'.join(parts)

def fixture_difficulty_score(upcoming):
    total = 0
    for val in upcoming:
        if val == "BLANK":
            total += 3
        elif "DGW" in str(val):
            total += 1.5
        elif '|' in str(val):
            try:
                total += int(str(val).split('|')[-1].strip())
            except ValueError:
                total += 3
        else:
            total += 3
    return round(total, 1)

def style_ticker(val):
    if pd.isna(val) or '|' not in str(val):
        return ''
    if "DGW" in str(val):
        return 'background-color: #38003c; color: white; font-weight: bold;'
    diff = int(str(val).split('|')[-1].strip())
    bg = DIFF_COLORS.get(diff, '')
    text = 'black' if diff in DIFF_LIGHT_TEXT else 'white'
    return f'background-color: {bg}; color: {text}; font-weight: bold;'

def style_ticker_row(row, my_team_names):
    if row['Team'] in my_team_names:
        return ['font-weight: bold; border-left: 4px solid #00ff85;'] + ['' for _ in row.index[1:]]
    return ['' for _ in row.index]

def get_display_df(df, cols):
    available = [c for c in cols if c in df.columns]
    return df[available].rename(columns={c: COLUMN_LABELS.get(c, c) for c in available})

def _compute_play_prob(row: pd.Series) -> float:
    """
    Rough play probability for next GW.
    Uses FPL's chance_of_playing_next_round when present, and downweights low-average-minutes players.
    """
    base = float(pd.to_numeric(row.get("chance_of_playing_next_round", 100), errors="coerce") or 100.0)
    avg_mins = float(pd.to_numeric(row.get("avg_minutes", 90), errors="coerce") or 90.0)
    news = str(row.get("news", "") or "")
    rot = str(row.get("rotation_risk", "") or "")

    # Minutes factor: below ~30 mins is very risky, 75+ is solid.
    mins_factor = max(0.15, min(1.0, avg_mins / 75.0))

    # Rotation/news penalties (heuristics).
    penalty = 1.0
    if "Low mins" in rot:
        penalty *= 0.85
    if news and news.lower() not in ("nan", "none"):
        penalty *= 0.9

    p = (base / 100.0) * mins_factor * penalty
    return round(max(0.0, min(1.0, p)), 2)


def _confidence_tier_from_play_prob(play_prob: float) -> str:
    if play_prob >= 0.8:
        return "High"
    if play_prob >= 0.6:
        return "Medium"
    return "Low"


def _variance_flags_for_team(*, team_id: int, horizon_gws: int) -> list[str]:
    """
    DGW/Blank variance flags over the projection horizon.
    """
    flags: list[str] = []
    try:
        curr_gw = next((e["id"] for e in data["events"] if e.get("is_current")), None)
        if not curr_gw:
            return flags
        for gw in range(curr_gw + 1, curr_gw + 1 + int(horizon_gws)):
            gw_fixtures = [f for f in fixtures_raw if f.get("event") == gw]
            if not gw_fixtures:
                continue
            teams_in_gw = [f["team_h"] for f in gw_fixtures] + [f["team_a"] for f in gw_fixtures]
            counts = pd.Series(teams_in_gw).value_counts()
            if int(team_id) not in counts.index:
                flags.append(f"Blank in GW{gw}")
            elif int(counts.loc[int(team_id)]) > 1:
                flags.append(f"DGW in GW{gw}")
    except Exception:
        return flags
    return flags


def gw_status_for(gw_id: int | None) -> dict:
    """
    Compute DGW/blank context for a specific GW.
    Returns dict with keys: kind, dgw_team_ids, active_team_ids, team_counts.
    """
    if not gw_id:
        return {"kind": "N/A", "dgw_team_ids": [], "active_team_ids": set(), "team_counts": pd.Series(dtype=int)}
    gw_fixtures = [f for f in fixtures_raw if f.get("event") == gw_id]
    if not gw_fixtures:
        return {"kind": "N/A", "dgw_team_ids": [], "active_team_ids": set(), "team_counts": pd.Series(dtype=int)}
    all_teams_playing = [f["team_h"] for f in gw_fixtures] + [f["team_a"] for f in gw_fixtures]
    team_counts = pd.Series(all_teams_playing).value_counts()
    dgw_team_ids = team_counts[team_counts > 1].index.tolist()
    active_team_ids = set(team_counts.index.tolist())
    kind = "Normal"
    if dgw_team_ids:
        kind = "Double Gameweek"
    return {
        "kind": kind,
        "dgw_team_ids": dgw_team_ids,
        "active_team_ids": active_team_ids,
        "team_counts": team_counts,
    }


def _team_list(team_ids: list[int]) -> str:
    if not team_ids:
        return "—"
    return ", ".join(sorted([team_short_map.get(int(t), str(t)) for t in team_ids]))


def build_team_fixture_weights(
    *,
    fixtures: list[dict],
    data: dict,
    horizon_gws: int,
) -> tuple[list[int], dict[int, list[float]]]:
    """
    For each team and each GW in the horizon, return a weight representing fixture favorability.

    Weight per fixture: (6 - difficulty) / 5  in [0.2..1.0]
    DGW: sum of weights across fixtures (so 2 fixtures ~ double opportunity)
    Blank: 0
    """
    try:
        base_gw = next(e["id"] for e in data["events"] if e["is_current"]) + 1
    except Exception:
        base_gw = 1

    gw_ids = list(range(base_gw, base_gw + horizon_gws))
    out: dict[int, list[float]] = {int(tid): [0.0] * horizon_gws for tid in team_map.keys()}

    for gi, gw in enumerate(gw_ids):
        gw_fixtures = [f for f in fixtures if f.get("event") == gw]
        for f in gw_fixtures:
            try:
                th = int(f["team_h"])
                ta = int(f["team_a"])
                dh = int(f["team_h_difficulty"])
                da = int(f["team_a_difficulty"])
            except Exception:
                continue

            out[th][gi] += max(0.0, min(1.0, (6 - dh) / 5))
            out[ta][gi] += max(0.0, min(1.0, (6 - da) / 5))

    return gw_ids, out


def add_projection_columns(df: pd.DataFrame, *, horizon_gws: int) -> pd.DataFrame:
    """
    Adds:
      - play_prob: 0..1
      - proj_pts: projected points over horizon using (form * fixture_weight_sum) * play_prob
    """
    if df.empty:
        return df.copy()
    proj = df.copy()
    proj["play_prob"] = proj.apply(_compute_play_prob, axis=1)
    proj["confidence_tier"] = proj["play_prob"].apply(lambda p: _confidence_tier_from_play_prob(float(p)))
    # If we don't have team ids, fall back to a form-only projection.
    if "team" not in proj.columns:
        proj["proj_pts"] = (pd.to_numeric(proj.get("form", 0), errors="coerce").fillna(0) * float(horizon_gws) * proj["play_prob"]).round(1)
        return proj

    gw_ids, w = build_team_fixture_weights(fixtures=fixtures_raw, data=data, horizon_gws=horizon_gws)
    proj["_fixture_weight_sum"] = proj["team"].apply(lambda tid: float(sum(w.get(int(tid), [0.0] * horizon_gws))))
    proj["proj_pts"] = (proj["form"] * proj["_fixture_weight_sum"] * proj["play_prob"]).round(1)
    proj["variance_flags"] = proj["team"].apply(lambda tid: ", ".join(_variance_flags_for_team(team_id=int(tid), horizon_gws=int(horizon_gws))) or "—")
    proj = proj.drop(columns=["_fixture_weight_sum"])
    return proj

def fetch_squad_picks(manager_id, gw_id):
    url = f"{FPL_BASE_URL}entry/{manager_id}/event/{gw_id}/picks/"
    try:
        return _fetch_json(url).get("picks", [])
    except requests.RequestException:
        return None

def df_to_csv(df):
    return df.to_csv(index=False).encode('utf-8')

def get_chip_status(used_chips):
    """
    Return dict of chip label -> status string.
    Uses the manager history `chips` list directly.

    We don't assume a specific rule-set (some seasons/rules have multiple uses).
    We simply report how many times each chip was played and in which GWs.
    """
    status: dict[str, str] = {}
    for chip_key, chip_label in ALL_CHIPS.items():
        uses = [c for c in (used_chips or []) if c.get("name") == chip_key]
        gws = []
        for u in uses:
            try:
                gw = int(u.get("event", 0) or 0)
            except Exception:
                gw = 0
            if gw > 0:
                gws.append(gw)
        gws = sorted(set(gws))

        if not gws:
            status[chip_label] = "Available"
        elif len(gws) == 1:
            status[chip_label] = f"Used (GW{gws[0]})"
        else:
            status[chip_label] = "Used (" + ", ".join([f"GW{g}" for g in gws]) + ")"
    return status

# ==========================================
# 7. SIDEBAR & SQUAD LOGIC
# ==========================================
_local_settings = load_local_settings()

st.sidebar.header("Manager Settings")

# --- Saved Profiles ---
profiles: dict = _local_settings.get("profiles", {}) if isinstance(_local_settings.get("profiles", {}), dict) else {}
profile_names = ["(default)"] + sorted([str(k) for k in profiles.keys()])
picked_profile = st.sidebar.selectbox(
    "Profile",
    options=profile_names,
    index=0,
    help="Save/load multiple manager setups (manager/rival/league + key settings).",
    key="profile_pick",
)

if picked_profile != "(default)":
    p = profiles.get(picked_profile, {})
    if isinstance(p, dict):
        if p.get("manager_id"):
            st.query_params["id"] = str(p.get("manager_id"))
            _local_settings["manager_id"] = str(p.get("manager_id"))
        if p.get("rival_id"):
            st.query_params["rival"] = str(p.get("rival_id"))
            _local_settings["rival_id"] = str(p.get("rival_id"))
        if p.get("league_id"):
            st.query_params["league"] = str(p.get("league_id"))
            _local_settings["league_id"] = str(p.get("league_id"))
        if p.get("fixture_lookahead"):
            _local_settings["fixture_lookahead"] = int(p.get("fixture_lookahead"))
        if isinstance(p.get("thresholds"), dict):
            _local_settings["thresholds"] = p.get("thresholds")

with st.sidebar.expander("Profiles", expanded=False):
    new_profile_name = st.text_input("Save current as", value="", key="profile_new_name")
    c1, c2 = st.columns(2)
    if c1.button("Save", use_container_width=True, key="profile_save_btn") and new_profile_name.strip():
        profiles[new_profile_name.strip()] = {
            "manager_id": str(_local_settings.get("manager_id", "")),
            "rival_id": str(_local_settings.get("rival_id", "")),
            "league_id": str(_local_settings.get("league_id", "")),
            "fixture_lookahead": int(_local_settings.get("fixture_lookahead", 5)),
            "thresholds": _local_settings.get("thresholds", {}),
        }
        _local_settings["profiles"] = profiles
        save_local_settings(_local_settings)
        st.success("Profile saved.")
    if c2.button("Delete", use_container_width=True, key="profile_delete_btn") and picked_profile != "(default)":
        profiles.pop(picked_profile, None)
        _local_settings["profiles"] = profiles
        save_local_settings(_local_settings)
        st.warning("Profile deleted.")

my_id = st.sidebar.text_input(
    "Manager ID",
    value=str(st.query_params.get("id", _local_settings.get("manager_id", ""))),
    help="Your FPL entry/manager ID (numbers only). Saved locally for next time.",
)
if my_id:
    st.query_params["id"] = my_id
    _local_settings["manager_id"] = my_id

fixture_lookahead = st.sidebar.slider(
    "Fixture Lookahead (GWs)",
    min_value=3,
    max_value=8,
    value=int(_local_settings.get("fixture_lookahead", 5)),
    help="Used in the Ticker and planning panels.",
)
_local_settings["fixture_lookahead"] = int(fixture_lookahead)

with st.sidebar.expander("Advanced Thresholds"):
    FORM_TC_THRESHOLD = st.slider("TC Form Min", 3.0, 9.0, FORM_TC_THRESHOLD, step=0.5,
                                  help="Minimum form score to suggest Triple Captain")
    BLANK_FREE_HIT_THRESHOLD = st.slider("FH Blank Threshold", 2, 6, BLANK_FREE_HIT_THRESHOLD,
                                         help="Blanked players needed to suggest Free Hit")
    DGW_BENCH_BOOST_THRESHOLD = st.slider("BB DGW Players", 2, 5, DGW_BENCH_BOOST_THRESHOLD,
                                           help="DGW players on bench to suggest Bench Boost")
    DIFF_MAX_OWNERSHIP = st.slider("Differential Cutoff %", 1.0, 20.0, float(DIFF_MAX_OWNERSHIP), step=1.0,
                                   help="Ownership threshold for differential status")
    _local_settings["thresholds"] = {
        "FORM_TC_THRESHOLD": float(FORM_TC_THRESHOLD),
        "BLANK_FREE_HIT_THRESHOLD": int(BLANK_FREE_HIT_THRESHOLD),
        "DGW_BENCH_BOOST_THRESHOLD": int(DGW_BENCH_BOOST_THRESHOLD),
        "DIFF_MAX_OWNERSHIP": float(DIFF_MAX_OWNERSHIP),
    }

if next_gw:
    dt = pd.to_datetime(next_gw['deadline_time']).strftime('%a %d %b %H:%M')
    st.sidebar.success(f"GW{next_gw['id']} Deadline: {dt}")

my_player_ids, my_squad, my_picks = [], pd.DataFrame(), []
my_team_ids = set()

if my_id and curr_gw_event:
    picks = fetch_squad_picks(my_id, curr_gw_id)
    if picks is None:
        st.sidebar.error("Could not sync squad.")
    else:
        my_picks = picks
        my_player_ids = [p['element'] for p in picks]
        my_squad = players[players['id'].isin(my_player_ids)].copy()
        my_team_ids = set(my_squad['team'].tolist())

        picks_df = pd.DataFrame(picks)[['element', 'multiplier', 'position']]
        picks_df = picks_df.rename(columns={'element': 'id'})
        my_squad = my_squad.merge(picks_df, on='id', how='left')

        if 'chance_of_playing_next_round' in my_squad.columns and 'news' in my_squad.columns:
            flagged = my_squad[my_squad['news'].astype(str).str.strip() != '']
            unavailable = flagged[flagged['chance_of_playing_next_round'] == 0]
            injured = flagged[
                (flagged['chance_of_playing_next_round'] > 0) &
                (flagged['chance_of_playing_next_round'] < 75)
            ]
            if not unavailable.empty:
                st.sidebar.error(f"Unavailable: {', '.join(unavailable['web_name'].tolist())}")
            if not injured.empty:
                for _, row in injured.iterrows():
                    st.sidebar.warning(f"{row['web_name']} — {int(row['chance_of_playing_next_round'])}% chance")

        # --- Gameweek Status (DGW/Blank/Normal) ---
        if next_gw:
            st.sidebar.markdown("---")
            st.sidebar.subheader("Gameweek Status")
            _gw_status = gw_status_for(next_gw["id"])
            _dgw_teams = _gw_status["dgw_team_ids"]
            _active_teams = _gw_status["active_team_ids"]
            _blank_team_ids = sorted([t for t in team_map.keys() if t not in _active_teams]) if _active_teams else []

            # Use stacked metrics in sidebar to avoid truncation on narrower sidebars.
            _kind = str(_gw_status["kind"])
            _kind_short = "DGW" if _kind == "Double Gameweek" else ("Blank" if _kind == "Blank" else "Normal")

            st.sidebar.metric(
                "Type",
                _kind_short,
                help="Normal = one fixture per team. DGW = a team has 2+ fixtures. Blanks are team-specific (your players may blank even in a normal GW).",
            )
            st.sidebar.metric(
                "DGW teams",
                int(len(_dgw_teams)),
                help="Count of teams with 2+ fixtures next GW.",
            )

            st.sidebar.caption(f"DGW teams: {_team_list([int(t) for t in _dgw_teams])}")

            # Squad impact
            my_dgw_players = my_squad[my_squad['team'].isin(_dgw_teams)]
            blank_players = my_squad[~my_squad['team'].isin(_active_teams)] if _active_teams else pd.DataFrame()
            st.sidebar.metric(
                "Your DGW players",
                int(len(my_dgw_players)),
                help="Players in your squad whose team has a DGW next GW.",
            )
            st.sidebar.metric(
                "Your blank players",
                int(len(blank_players)),
                help="Players in your squad whose team has no fixture next GW.",
            )

            if len(blank_players) > 0:
                st.sidebar.warning(f"Blanking: {', '.join(blank_players['web_name'].tolist())}")

        st.sidebar.markdown("---")
        st.sidebar.subheader("Chip Strategy")

        if next_gw:
            gw_fixtures = [f for f in fixtures_raw if f['event'] == next_gw['id']]
            all_teams_playing = [f['team_h'] for f in gw_fixtures] + [f['team_a'] for f in gw_fixtures]
            team_counts = pd.Series(all_teams_playing).value_counts()
            dgw_teams = team_counts[team_counts > 1].index.tolist()
            my_dgw_players = my_squad[my_squad['team'].isin(dgw_teams)]
            active_teams = set(team_counts.index)
            blank_players = my_squad[~my_squad['team'].isin(active_teams)]
            blanks = len(blank_players)

            if not blank_players.empty:
                st.sidebar.warning(f"GW{next_gw['id']} Blanks: {', '.join(blank_players['web_name'].tolist())}")
            if blanks >= BLANK_FREE_HIT_THRESHOLD:
                st.sidebar.error(f"Free Hit Advised! ({blanks} blanks)")
            elif not my_dgw_players.empty:
                tc_cand = my_dgw_players.nlargest(1, 'form')
                if not tc_cand.empty and tc_cand.iloc[0]['form'] > FORM_TC_THRESHOLD:
                    st.sidebar.warning(f"Triple Captain {tc_cand.iloc[0]['web_name']} (DGW!)")
                elif len(my_dgw_players) >= DGW_BENCH_BOOST_THRESHOLD:
                    st.sidebar.success(f"Bench Boost! ({len(my_dgw_players)} DGW players)")
                else:
                    st.sidebar.info("Active DGW players. Good luck!")
            elif blanks > 0:
                st.sidebar.warning(f"{blanks} Blanks. Use FT.")
            else:
                st.sidebar.info("Save Chips. No DGW/Blanks.")

        # Save settings once we've successfully loaded squad (best-effort).
        save_local_settings(_local_settings)

# ==========================================
# 8. MAIN DASHBOARD TABS
# ==========================================
tabs = st.tabs([
    "My Team", "Live GW", "GW History", "Global Scout", "Price Changes",
    "Ticker", "Player VS", "Mini-League", "Rivals", "Transfers", "Wildcard"
])

# ── TAB 0: MY TEAM ──────────────────────────────────────────────────────────
with tabs[0]:
    if not my_squad.empty:
        st.header("Squad Performance")
        m1, m2, m3, m4 = st.columns(4)
        try:
            entry = get_manager_entry(my_id)
            overall_pts = entry.get('summary_overall_points', 'N/A')
            overall_rank = entry.get('summary_overall_rank', None)
        except requests.RequestException:
            overall_pts, overall_rank = 'N/A', None
        m1.metric("Overall Pts", overall_pts)
        m2.metric("Squad xG", round(my_squad['expected_goals'].sum(), 2))
        m3.metric("Avg Form", round(my_squad['form'].mean(), 1))
        m4.metric("Squad Value", f"£{my_squad['price'].sum():.1f}m")
        if overall_rank:
            st.caption(f"Overall Rank: {overall_rank:,}")

        squad_cols = [
            'web_name', 'team_name', 'pos', 'price',
            'xpts', 'proj_pts', 'play_prob',
            'form', 'form_trend',
            'expected_goals', 'expected_assists', 'expected_goal_involvements', 'expected_goals_conceded',
            'ppm', 'total_points', 'ict_index',
            'avg_minutes', 'rotation_risk', 'selected_by_percent',
        ]
        starters = my_squad[my_squad['multiplier'] > 0].sort_values('position')
        bench = my_squad[my_squad['multiplier'] == 0].sort_values('position')

        st.subheader("Starting XI")
        st.dataframe(get_display_df(starters, squad_cols), width="stretch", hide_index=True)

        # --- Bench Analysis ---
        st.subheader("Bench")
        st.dataframe(get_display_df(bench, squad_cols), width="stretch", hide_index=True)

        bb_estimate = round(bench['form'].sum(), 1)
        bench_season_pts = int(bench['total_points'].sum())
        remaining_gws = (38 - curr_gw_id) if curr_gw_id else 0
        ba1, ba2, ba3 = st.columns(3)
        ba1.metric("Bench Season Total Pts", bench_season_pts, help="Sum of current bench players' full-season points")
        ba2.metric("Bench Boost Value (est.)", bb_estimate, help="Sum of bench players' form — proxy for single-GW value")
        ba3.metric("GWs Remaining", remaining_gws)

        # --- Form vs Season Average Chart ---
        st.markdown("---")
        st.subheader("Form vs Season Average")
        st.caption("Bar chart comparing each player's recent form (last 5 GW avg) against their season points-per-game.")
        _squad_sorted = my_squad.sort_values('pos')
        fig_form_avg = go.Figure()
        fig_form_avg.add_trace(go.Bar(
            x=_squad_sorted['web_name'], y=_squad_sorted['form'],
            name='Recent Form (last 5 GW avg)', marker_color='#38003c',
        ))
        fig_form_avg.add_trace(go.Bar(
            x=_squad_sorted['web_name'], y=_squad_sorted['season_ppg'],
            name='Season Avg Pts/GW', marker_color='#01fc7a',
            opacity=0.75,
        ))
        fig_form_avg.update_layout(
            barmode='group', xaxis_title='Player', yaxis_title='Points',
            xaxis_tickangle=-35, legend=dict(orientation='h'),
            margin=dict(l=40, r=40, t=20, b=100),
        )
        st.plotly_chart(fig_form_avg, width="stretch")

        # --- XI Optimizer + Bench Order ---
        st.markdown("---")
        st.header("XI Optimizer & Bench Order")
        st.caption("Uses projected points (form × fixtures × play probability) to suggest your best XI and bench order.")

        _horizon = st.slider(
            "Projection horizon (GWs)",
            min_value=2,
            max_value=5,
            value=3,
            help="Longer horizon emphasizes fixture runs; shorter horizon is more reactive.",
            key="xi_horizon",
        )
        squad_proj = add_projection_columns(my_squad, horizon_gws=int(_horizon))

        try:
            from fpl.logic import optimize_starting_xi as _opt_xi  # type: ignore
            xi_df, bench_df = _opt_xi(squad_proj, score_col="proj_pts", pos_col="pos")
        except Exception:
            xi_df = squad_proj.sort_values("proj_pts", ascending=False).head(11).copy()
            bench_df = squad_proj.drop(index=xi_df.index).sort_values("proj_pts", ascending=False).copy()

        xi_cols = [
            "web_name",
            "team_name",
            "pos",
            "price",
            "proj_pts",
            "play_prob",
            "confidence_tier",
            "variance_flags",
            "xpts",
            "form",
            "expected_goals",
            "expected_assists",
            "expected_goal_involvements",
            "expected_goals_conceded",
            "rotation_risk",
            "selected_by_percent",
        ]
        st.subheader("Suggested Starting XI")
        st.dataframe(get_display_df(xi_df, xi_cols), width="stretch", hide_index=True)

        st.subheader("Suggested Bench Order")
        b = bench_df.copy()
        b_gk = b[b["pos"] == "GKP"].sort_values("proj_pts", ascending=False)
        b_out = b[b["pos"] != "GKP"].sort_values("proj_pts", ascending=False)
        bench_ordered = pd.concat([b_out, b_gk], ignore_index=True)
        st.dataframe(get_display_df(bench_ordered, xi_cols), width="stretch", hide_index=True)

        st.download_button(
            "Download XI plan CSV",
            df_to_csv(get_display_df(pd.concat([xi_df.assign(role="Starting XI"), bench_ordered.assign(role="Bench")]), ["role"] + xi_cols)),
            file_name="xi_bench_plan.csv",
            mime="text/csv",
            help="Exports the suggested XI and bench order.",
        )

        # --- Captaincy Predictor ---
        st.markdown("---")
        st.header("Captaincy Predictor")
        if next_gw:
            try:
                opp_map = {}
                for f in [f for f in fixtures_raw if f['event'] == next_gw['id']]:
                    opp_map[f['team_h']] = {'opp': team_map[f['team_a']], 'diff': f['team_h_difficulty'], 'loc': 'H'}
                    opp_map[f['team_a']] = {'opp': team_map[f['team_h']], 'diff': f['team_a_difficulty'], 'loc': 'A'}

                cap_df = my_squad.copy()
                cap_df['Opp'] = cap_df['team'].apply(lambda x: opp_map.get(x, {}).get('opp', 'N/A'))
                cap_df['Diff'] = cap_df['team'].apply(lambda x: opp_map.get(x, {}).get('diff', 3))
                cap_df['Loc'] = cap_df['team'].apply(lambda x: opp_map.get(x, {}).get('loc', 'A'))
                # Enhanced formula: Form 45% + ICT (normalised) 30% + Fixture 20% + Home 5%
                _max_ict = float(players['ict_index'].max()) or 1.0
                cap_df['ict_norm'] = (cap_df['ict_index'].astype(float) / _max_ict * 10).round(1)
                cap_df['Score'] = (
                    cap_df['form'] * 0.45 +
                    cap_df['ict_norm'] * 0.30 +
                    (6 - cap_df['Diff']) * 0.20 +
                    cap_df['Loc'].apply(lambda loc: HOME_CAPTAIN_BONUS if loc == 'H' else 0)
                ).round(2)
                cap_df['Tier'] = cap_df['Score'].apply(
                    lambda s: 'A — Strong' if s > 4 else ('B — Solid' if s >= 2.5 else 'C — Risky')
                )

                # Add projections + a confidence proxy
                cap_df = add_projection_columns(cap_df, horizon_gws=2)
                cap_df["Confidence"] = (cap_df["play_prob"] * 100).round(0).astype(int)
                _conf = cap_df.apply(lambda r: captain_confidence(r), axis=1, result_type="expand")
                cap_df["confidence_tier"] = _conf[0]
                cap_df["confidence_flags"] = _conf[1].apply(lambda xs: ", ".join(xs) if xs else "—")

                c_cols = st.columns(3)
                for i, (_, row) in enumerate(cap_df.nlargest(3, 'Score').iterrows()):
                    with c_cols[i]:
                        st.subheader(f"#{i+1}: {row['web_name']}")
                        st.write(f"vs **{row['Opp']}** ({row['Loc']})")
                        d = row['Diff']
                        color = "green" if d <= 2 else "orange" if d <= 3 else "red"
                        st.markdown(f"Difficulty: :{color}[Level {d}]")
                        st.metric("Cap Score", row['Score'])
                        st.caption(
                            f"Tier: {row['Tier']}  |  Projected (2GW): {row['proj_pts']}  |  "
                            f"Confidence: {row['confidence_tier']} ({row['Confidence']}%)"
                        )
                        if row.get("confidence_flags", "—") != "—":
                            st.caption(f"Flags: {row['confidence_flags']}")

                        # Reason codes for the top pick (keeps UI compact)
                        if i == 0:
                            with st.expander("Why this captain? (reason breakdown)", expanded=False):
                                rb = captain_reason_breakdown(
                                    row,
                                    max_ict=_max_ict,
                                    home_captain_bonus=float(HOME_CAPTAIN_BONUS),
                                )
                                st.dataframe(rb, width="stretch", hide_index=True)

                st.markdown("---")
                st.subheader("Captaincy Matrix")
                st.caption("Ranked table using Cap Score + projected points + minutes confidence.")
                _matrix = cap_df.copy()
                _matrix["Captain Rank Score"] = (
                    _matrix["Score"] * 0.6 + _matrix["proj_pts"] * 0.4
                ).round(2)
                mcols = [
                    "web_name",
                    "team_name",
                    "pos",
                    "Opp",
                    "Loc",
                    "Diff",
                    "Score",
                    "proj_pts",
                    "Confidence",
                    "confidence_tier",
                    "confidence_flags",
                    "variance_flags",
                    "Captain Rank Score",
                ]
                st.dataframe(
                    get_display_df(_matrix.sort_values("Captain Rank Score", ascending=False), mcols).head(15),
                    use_container_width=True,
                    hide_index=True,
                )

                # On-demand reason breakdown (keeps the matrix clean)
                st.markdown("---")
                st.subheader("On-demand: captain reasoning")
                st.caption("Pick any candidate to see the weighted reason breakdown + confidence flags.")

                ranked = _matrix.sort_values("Captain Rank Score", ascending=False).reset_index(drop=True)
                _pick_names = ranked.head(15)["web_name"].tolist()
                _default_name = str(_pick_names[0]) if _pick_names else ""
                _picked_name = st.selectbox(
                    "Show reasoning for",
                    options=_pick_names,
                    index=0,
                    help="Select a player to see the reason breakdown and confidence details.",
                    key="capt_reason_pick",
                )
                _picked = ranked[ranked["web_name"] == _picked_name].head(1)
                if not _picked.empty:
                    _row = _picked.iloc[0]
                    r1, r2 = st.columns([1.2, 1])
                    with r1:
                        st.markdown(f"**Weighted reason breakdown — {_picked_name}**")
                        rb = captain_reason_breakdown(
                            _row,
                            max_ict=_max_ict,
                            home_captain_bonus=float(HOME_CAPTAIN_BONUS),
                        )
                        st.dataframe(rb, width="stretch", hide_index=True)
                    with r2:
                        st.markdown("**Confidence + context**")
                        st.metric("Confidence tier", _row.get("confidence_tier", "—"))
                        st.metric("Minutes confidence", f"{int(_row.get('Confidence', 0))}%")
                        st.caption(f"Flags: {_row.get('confidence_flags', '—')}")
                        st.caption(f"Opponent: {_row.get('Opp', '—')} ({_row.get('Loc', '—')}), difficulty {int(_row.get('Diff', 3))}")
                        st.caption(f"Captain Rank Score: {_row.get('Captain Rank Score', '—')} (Score×0.6 + proj×0.4)")

                # "Why not" near-misses (adds context beyond the top pick)
                st.markdown("---")
                st.subheader("Why not the next-best picks?")
                st.caption("Near-miss notes comparing each candidate to the #1 captain.")
                if len(ranked) >= 4:
                    winner = ranked.iloc[0]
                    for j in range(1, min(5, len(ranked))):
                        cand = ranked.iloc[j]
                        notes = why_not_notes(candidate=cand, winner=winner)
                        if not notes:
                            notes = ["Very close — mostly preference / variance."]
                        st.markdown(
                            f"**#{j+1}: {cand['web_name']}** — " + "; ".join(notes)
                        )

                st.download_button(
                    "Download captaincy matrix CSV",
                    df_to_csv(get_display_df(_matrix.sort_values("Captain Rank Score", ascending=False), mcols)),
                    file_name="captaincy_matrix.csv",
                    mime="text/csv",
                )

                # --- Weekly One‑Click Plan Brief ---
                st.markdown("---")
                st.header("Weekly One‑Click Plan")
                st.caption("A single digest: captain, VC, XI, bench order, quick transfer idea, chip note, key risks.")

                captain = ranked.iloc[0] if len(ranked) > 0 else None
                vice = ranked.iloc[1] if len(ranked) > 1 else None

                # Quick transfer idea (lightweight): identify your lowest projected player.
                _low = squad_proj.sort_values("proj_pts", ascending=True).head(1)
                transfer_idea = None
                if not _low.empty:
                    transfer_idea = f"Consider upgrading **{_low.iloc[0]['web_name']}** (low projected points)."

                # Chip note (reuse same heuristics as sidebar, computed locally here).
                chip_note = None
                if next_gw:
                    gw_fixtures = [f for f in fixtures_raw if f.get("event") == next_gw["id"]]
                    if gw_fixtures:
                        all_teams_playing = [f["team_h"] for f in gw_fixtures] + [f["team_a"] for f in gw_fixtures]
                        team_counts = pd.Series(all_teams_playing).value_counts()
                        dgw_teams = team_counts[team_counts > 1].index.tolist()
                        active_teams = set(team_counts.index)
                        blank_players = my_squad[~my_squad["team"].isin(active_teams)]
                        my_dgw_players = my_squad[my_squad["team"].isin(dgw_teams)]
                        if len(blank_players) >= BLANK_FREE_HIT_THRESHOLD:
                            chip_note = f"Free Hit candidate: **{len(blank_players)}** blanking players."
                        elif len(my_dgw_players) >= DGW_BENCH_BOOST_THRESHOLD:
                            chip_note = f"Bench Boost candidate: **{len(my_dgw_players)}** DGW players in squad."
                        elif len(dgw_teams) > 0:
                            chip_note = "Double Gameweek upcoming — consider targeting DGW minutes certainty."

                # Risks: low confidence starters + flagged news
                risks: list[str] = []
                _low_conf_starters = xi_df[xi_df["play_prob"] < 0.6]["web_name"].tolist() if "play_prob" in xi_df.columns else []
                if _low_conf_starters:
                    risks.append("Low minutes confidence in XI: " + ", ".join(_low_conf_starters))
                if "chance_of_playing_next_round" in my_squad.columns:
                    _chance = pd.to_numeric(my_squad["chance_of_playing_next_round"], errors="coerce").fillna(100)
                else:
                    _chance = pd.Series([100] * len(my_squad), index=my_squad.index)
                if "news" in my_squad.columns:
                    _news = my_squad["news"].astype(str).fillna("")
                else:
                    _news = pd.Series([""] * len(my_squad), index=my_squad.index)
                _flagged = my_squad[(_chance < 75) & (_news.str.len() > 0)]
                if not _flagged.empty:
                    risks.append("Injury/rotation flags present (see sidebar warnings).")

                plan_md = build_one_click_plan_markdown(
                    gw_id=next_gw["id"] if next_gw else None,
                    captain=captain,
                    vice=vice,
                    xi_df=xi_df,
                    bench_df=bench_ordered,
                    chip_note=chip_note,
                    transfer_idea=transfer_idea,
                    risks=risks,
                )
                st.markdown(plan_md)
                st.download_button(
                    "Download plan (Markdown)",
                    data=plan_md,
                    file_name=f"weekly_plan_gw{next_gw['id'] if next_gw else 'na'}.md",
                    mime="text/markdown",
                    help="Exports the weekly plan as a Markdown file.",
                )

                # --- Export bundle (ZIP) ---
                with st.expander("Export bundle", expanded=False):
                    st.caption("Download a single zip with your weekly plan and key tables.")
                    try:
                        _players_proj = add_projection_columns(players.copy(), horizon_gws=2)
                        _eo_local = eo_risk_panel(
                            players=_players_proj,
                            my_squad_ids=set([int(x) for x in my_player_ids]),
                            captain_id=int(captain["id"]) if captain is not None else None,
                            template_top_n=30,
                            differential_own_cutoff=float(DIFF_MAX_OWNERSHIP),
                        )
                        bundle = io.BytesIO()
                        with zipfile.ZipFile(bundle, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                            gw_tag = f"gw{next_gw['id']}" if next_gw else "gwna"
                            zf.writestr(f"{gw_tag}/weekly_plan.md", plan_md)
                            # Captaincy matrix (top 15)
                            zf.writestr(
                                f"{gw_tag}/captaincy_matrix.csv",
                                get_display_df(_matrix.sort_values("Captain Rank Score", ascending=False), mcols).to_csv(index=False),
                            )
                            # EO tables
                            zf.writestr(
                                f"{gw_tag}/eo_threats.csv",
                                get_display_df(_eo_local["threats_df"], ["web_name", "team_name", "pos", "selected_by_percent", "proj_pts", "confidence_tier", "variance_flags", "threat_score"]).to_csv(index=False),
                            )
                            zf.writestr(
                                f"{gw_tag}/eo_differentials.csv",
                                get_display_df(_eo_local["differentials_df"], ["web_name", "team_name", "pos", "selected_by_percent", "proj_pts", "confidence_tier", "variance_flags", "play_prob"]).to_csv(index=False),
                            )
                            # XI plan
                            zf.writestr(
                                f"{gw_tag}/xi_bench_plan.csv",
                                get_display_df(
                                    pd.concat([xi_df.assign(role="Starting XI"), bench_ordered.assign(role="Bench")]),
                                    ["role"] + xi_cols,
                                ).to_csv(index=False),
                            )
                        bundle.seek(0)
                        st.download_button(
                            "Download weekly bundle.zip",
                            data=bundle.getvalue(),
                            file_name=f"weekly_bundle_{gw_tag}.zip",
                            mime="application/zip",
                        )
                    except Exception as e:
                        st.warning(f"Could not build export bundle: {e}")

                # --- Chip Simulators (lightweight heuristics) ---
                with st.expander("Chip simulators (estimates)", expanded=False):
                    st.caption("Heuristic estimates based on projected points. Use as guidance, not a guarantee.")
                    if captain is not None:
                        # Triple Captain: extra over normal captaincy is +1× captain projected points.
                        tc_extra = float(pd.to_numeric(captain.get("proj_pts", 0), errors="coerce") or 0.0)
                        st.metric(
                            "Triple Captain — estimated extra points",
                            round(tc_extra, 1),
                            help="Approx extra vs normal captain: +1× captain projected points for the horizon.",
                        )
                    # Bench Boost: approximate extra points from bench players.
                    if "proj_pts" in bench_ordered.columns:
                        bb_extra = float(pd.to_numeric(bench_ordered["proj_pts"], errors="coerce").fillna(0.0).sum())
                        st.metric(
                            "Bench Boost — estimated bench points",
                            round(bb_extra, 1),
                            help="Approx points from bench if all play, using the same projection horizon as the XI optimizer.",
                        )
                    # Free Hit: highlight if you have many blanks next GW.
                    if next_gw:
                        gw_fixtures = [f for f in fixtures_raw if f.get("event") == next_gw["id"]]
                        if gw_fixtures:
                            all_teams_playing = [f["team_h"] for f in gw_fixtures] + [f["team_a"] for f in gw_fixtures]
                            active_teams = set(pd.Series(all_teams_playing).value_counts().index.tolist())
                            blanks = my_squad[~my_squad["team"].isin(active_teams)]
                            st.metric(
                                "Free Hit — blanking players",
                                int(len(blanks)),
                                help="Counts your squad players whose team has no fixture in the next GW.",
                            )
                            if len(blanks) > 0:
                                st.caption("Blanking: " + ", ".join(blanks["web_name"].tolist()))
                    # Variance note
                    if "variance_flags" in squad_proj.columns:
                        _var = squad_proj["variance_flags"].astype(str)
                        if _var.str.contains("DGW").any():
                            st.info("DGW variance: projections may be higher but minutes risk is also higher (rotation/early subs).")

                # --- EO / Template Risk Panel ---
                st.markdown("---")
                st.header("EO / Template Risk")
                st.caption("Ownership-based risk proxy: how well you're shielded vs the template, and where your upside lives.")

                players_proj = add_projection_columns(players.copy(), horizon_gws=2)
                # Captaincy scenario explorer: pick an assumed template captain.
                _top_owned = players_proj.sort_values("selected_by_percent", ascending=False).head(12).copy()
                _templ_opts = _top_owned["web_name"].tolist()
                _templ_default = _templ_opts[0] if _templ_opts else None
                _template_cap_name = st.selectbox(
                    "Assumed template captain",
                    options=_templ_opts,
                    index=0,
                    help="Used to estimate rank-protection risk. Default is the most-owned player.",
                    key="template_captain_assumption",
                )
                _template_cap_row = _top_owned[_top_owned["web_name"] == _template_cap_name].head(1)
                _template_cap_id = int(_template_cap_row.iloc[0]["id"]) if not _template_cap_row.empty else None
                _template_cap_owned = (_template_cap_id in set([int(x) for x in my_player_ids])) if _template_cap_id else False

                if _template_cap_id and not _template_cap_owned:
                    st.warning(f"Template captain risk: you do **not** own **{_template_cap_name}**.")

                eo = eo_risk_panel(
                    players=players_proj,
                    my_squad_ids=set([int(x) for x in my_player_ids]),
                    captain_id=int(captain["id"]) if captain is not None else None,
                    template_top_n=30,
                    differential_own_cutoff=float(DIFF_MAX_OWNERSHIP),
                )

                e1, e2 = st.columns(2)
                e1.metric("Shield score", eo["shield_score"], help="Coverage vs top-owned template players (captain adds extra). Higher = safer.")
                e2.metric("Attack score", eo["attack_score"], help="Upside from low-owned players with projection. Higher = more aggressive.")

                # Simple captaincy swing proxy
                if _template_cap_id and captain is not None:
                    _my_cap_name = str(captain.get("web_name", "—"))
                    if _template_cap_name != _my_cap_name:
                        _templ_own = float(pd.to_numeric(_template_cap_row.iloc[0].get("selected_by_percent", 0), errors="coerce") or 0.0) if not _template_cap_row.empty else 0.0
                        _templ_proj = float(pd.to_numeric(_template_cap_row.iloc[0].get("proj_pts", 0), errors="coerce") or 0.0) if not _template_cap_row.empty else 0.0
                        st.caption(
                            f"Captaincy scenario: if the template captains **{_template_cap_name}** (~{_templ_own:.0f}% owned), "
                            f"your choice (**{_my_cap_name}**) is a higher-variance play."
                        )

                t1, t2 = st.columns(2)
                with t1:
                    st.subheader("Top threats (template players you don't own)")
                    threats_cols = ["web_name", "team_name", "pos", "selected_by_percent", "proj_pts", "confidence_tier", "variance_flags", "threat_score"]
                    st.dataframe(get_display_df(eo["threats_df"], threats_cols), width="stretch", hide_index=True)
                with t2:
                    st.subheader("Your differentials (low-owned upside)")
                    diff_cols = ["web_name", "team_name", "pos", "selected_by_percent", "proj_pts", "confidence_tier", "variance_flags", "play_prob"]
                    st.dataframe(get_display_df(eo["differentials_df"], diff_cols), width="stretch", hide_index=True)

                # EO threat explainability (on demand)
                with st.expander("Why is a player a threat?", expanded=False):
                    _th = eo["threats_df"].copy()
                    if not _th.empty:
                        _th_names = _th["web_name"].tolist()
                        _th_pick = st.selectbox("Threat player", options=_th_names, index=0, key="eo_threat_pick")
                        _row = _th[_th["web_name"] == _th_pick].head(1).iloc[0]
                        st.markdown(f"**{_th_pick}**")
                        st.caption(f"Ownership: {float(_row.get('selected_by_percent', 0)):.1f}%")
                        st.caption(f"Projection: {float(_row.get('proj_pts', 0)):.1f} | Confidence: {_row.get('confidence_tier', '—')} | Variance: {_row.get('variance_flags', '—')}")
                        st.caption(f"Threat score ≈ ownership × projection: {float(_row.get('threat_score', 0)):.1f}")
                    else:
                        st.info("No threats found.")

                # --- Threat Radar (summary) ---
                st.markdown("---")
                st.header("Threat Radar")
                st.caption("Quick answers: what can hurt you this week, and where your upside is coming from.")
                r1, r2, r3 = st.columns(3)
                # Blanks / DGW in your squad next GW
                if next_gw:
                    _gw = next_gw["id"]
                    _st = gw_status_for(_gw)
                    _active = _st["active_team_ids"]
                    _blanks = my_squad[~my_squad["team"].isin(_active)] if _active else pd.DataFrame()
                    _dgw_team_ids = set(_st["dgw_team_ids"])
                    _dgw_players = my_squad[my_squad["team"].isin(_dgw_team_ids)] if _dgw_team_ids else pd.DataFrame()
                    r1.metric("Blanking players", int(len(_blanks)), help="Players in your squad with no fixture next GW.")
                    r2.metric("DGW players", int(len(_dgw_players)), help="Players in your squad whose team has a DGW next GW.")
                else:
                    r1.metric("Blanking players", "—")
                    r2.metric("DGW players", "—")
                # Captaincy threat
                r3.metric(
                    "Template captain owned?",
                    "Yes" if _template_cap_owned else "No",
                    help="Based on the assumed template captain in the EO panel.",
                )

                if next_gw and not _blanks.empty:
                    st.warning("Blanking: " + ", ".join(_blanks["web_name"].tolist()))
                if next_gw and not _dgw_players.empty:
                    st.info("DGW squad: " + ", ".join(_dgw_players["web_name"].tolist()))
            except (KeyError, ValueError):
                st.info("Fixture data pending.")
        else:
            st.info("Fixture data pending.")

        # --- Chip Tracker ---
        st.markdown("---")
        st.header("Chip Tracker")
        try:
            history = get_manager_history(my_id)
            used_chips = history.get('chips', [])
            chip_status = get_chip_status(used_chips)
            chip_cols = st.columns(len(chip_status))
            for col, (chip_label, status) in zip(chip_cols, chip_status.items()):
                col.metric(chip_label, status)

            with st.expander("Chip history (debug)", expanded=False):
                st.caption("Raw `history['chips']` from the FPL API. If this is empty, the API isn't returning chip usage.")
                st.json(used_chips[:20])
        except requests.RequestException:
            st.warning("Could not load chip data.")

    else:
        st.info("Enter your Manager ID in the sidebar to view your team.")

# ── TAB 1: LIVE GW ──────────────────────────────────────────────────────────
with tabs[1]:
    st.header("Live Gameweek Tracker")
    if curr_gw_event:
        st.caption(f"Showing live stats for GW{curr_gw_id}. Data refreshes every 60 seconds.")
        if st.button("Refresh live data"):
            get_live_gw_data.clear()

        try:
            live_data = get_live_gw_data(curr_gw_id)
            live_elements = live_data.get('elements', [])
            live_map = {e['id']: e['stats'] for e in live_elements}

            if not my_squad.empty:
                live_squad = my_squad.copy()
                live_squad['live_pts'] = live_squad['id'].apply(
                    lambda pid: live_map.get(pid, {}).get('total_points', 0)
                )
                live_squad['live_bonus'] = live_squad['id'].apply(
                    lambda pid: live_map.get(pid, {}).get('bonus', 0)
                )
                live_squad['live_minutes'] = live_squad['id'].apply(
                    lambda pid: live_map.get(pid, {}).get('minutes', 0)
                )
                live_squad['live_goals'] = live_squad['id'].apply(
                    lambda pid: live_map.get(pid, {}).get('goals_scored', 0)
                )
                live_squad['live_assists'] = live_squad['id'].apply(
                    lambda pid: live_map.get(pid, {}).get('assists', 0)
                )

                # Captain gets double points
                live_squad['effective_pts'] = live_squad.apply(
                    lambda r: r['live_pts'] * r['multiplier'], axis=1
                )

                total_live = int(live_squad['effective_pts'].sum())
                bench_live = int(live_squad[live_squad['multiplier'] == 0]['live_pts'].sum())
                lv1, lv2, lv3 = st.columns(3)
                lv1.metric("Live GW Points", total_live)
                lv2.metric("Bench Pts (unused)", bench_live)
                lv3.metric("GW Average", gw_averages.get(curr_gw_id, 'N/A'))

                # Add rich baseline metrics to live tables.
                live_squad = add_projection_columns(live_squad, horizon_gws=3)
                live_cols = [
                    'web_name', 'team_name', 'pos', 'price',
                    'proj_pts', 'play_prob',
                    'expected_goals', 'expected_assists', 'expected_goal_involvements', 'expected_goals_conceded',
                    'live_minutes', 'live_pts', 'live_bonus', 'live_goals', 'live_assists', 'multiplier',
                    'selected_by_percent',
                ]
                live_rename = {
                    'web_name': 'Player',
                    'team_name': 'Team',
                    'pos': 'Pos',
                    'price': '£m',
                    'proj_pts': 'Proj (3GW)',
                    'play_prob': 'Play Prob',
                    'expected_goals': 'xG',
                    'expected_assists': 'xA',
                    'expected_goal_involvements': 'xGI',
                    'expected_goals_conceded': 'xGC',
                    'live_minutes': 'Mins',
                    'live_pts': 'GW Pts',
                    'live_bonus': 'Bonus',
                    'live_goals': 'Goals',
                    'live_assists': 'Assists',
                    'multiplier': 'Mult',
                    'selected_by_percent': 'Own%',
                }
                live_starters = live_squad[live_squad['multiplier'] > 0].sort_values('position')
                live_bench = live_squad[live_squad['multiplier'] == 0].sort_values('position')

                st.subheader("Starting XI — Live")
                display_live = live_starters[[c for c in live_cols if c in live_starters.columns]]
                st.dataframe(display_live.rename(columns=live_rename), width="stretch", hide_index=True)

                st.subheader("Bench — Live")
                display_bench = live_bench[[c for c in live_cols if c in live_bench.columns]]
                st.dataframe(display_bench.rename(columns=live_rename), width="stretch", hide_index=True)
            else:
                st.info("Enter your Manager ID in the sidebar to see live squad points.")

            # All players live leaderboard
            st.markdown("---")
            st.subheader("Top Scoring Players This GW (Live)")
            live_df = pd.DataFrame([
                {'id': e['id'], 'live_pts': e['stats']['total_points'],
                 'live_bonus': e['stats'].get('bonus', 0),
                 'live_minutes': e['stats'].get('minutes', 0)}
                for e in live_elements
            ])
            if not live_df.empty:
                live_df = live_df.merge(
                    players[
                        [
                            'id', 'team', 'web_name', 'team_name', 'pos', 'price', 'selected_by_percent',
                            'expected_goals', 'expected_assists', 'expected_goal_involvements', 'expected_goals_conceded',
                            'form', 'ict_index',
                        ]
                    ],
                    on='id',
                    how='left',
                )
                live_df = add_projection_columns(live_df, horizon_gws=3)
                top_live_cols = [
                    'web_name', 'team_name', 'pos', 'price',
                    'proj_pts', 'play_prob',
                    'expected_goals', 'expected_assists', 'expected_goal_involvements', 'expected_goals_conceded',
                    'live_pts', 'live_bonus', 'live_minutes',
                    'selected_by_percent',
                ]
                top_live_rename = {
                    'web_name': 'Player', 'team_name': 'Team', 'pos': 'Pos', 'price': '£m',
                    'proj_pts': 'Proj (3GW)', 'play_prob': 'Play Prob',
                    'expected_goals': 'xG', 'expected_assists': 'xA', 'expected_goal_involvements': 'xGI', 'expected_goals_conceded': 'xGC',
                    'live_pts': 'GW Pts', 'live_bonus': 'Bonus', 'live_minutes': 'Mins',
                    'selected_by_percent': 'Own%',
                }
                st.dataframe(
                    live_df.sort_values('live_pts', ascending=False)
                    .head(20)[[c for c in top_live_cols if c in live_df.columns]]
                    .rename(columns=top_live_rename),
                    use_container_width=True, hide_index=True,
                )
        except requests.RequestException:
            st.warning("Live data unavailable. The gameweek may not have started yet.")
    else:
        st.info("No active gameweek found.")

# ── TAB 2: GW HISTORY ───────────────────────────────────────────────────────
with tabs[2]:
    st.header("Gameweek History & Points Trend")
    if my_id:
        try:
            history = get_manager_history(my_id)
            gw_history = history.get('current', [])
            if gw_history:
                hist_df = pd.DataFrame(gw_history)
                hist_df['gw_average'] = hist_df['event'].map(gw_averages)

                h1, h2, h3, h4 = st.columns(4)
                h1.metric("Season Total", int(hist_df['total_points'].iloc[-1]))
                h2.metric("Best GW", int(hist_df['points'].max()))
                h3.metric("Avg GW Score", round(hist_df['points'].mean(), 1))
                h4.metric("Overall Rank", f"{hist_df['overall_rank'].iloc[-1]:,}")

                # Points + average overlay
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=hist_df['event'], y=hist_df['points'],
                    name='Your GW Points', marker_color='#38003c', opacity=0.8,
                ))
                fig.add_trace(go.Scatter(
                    x=hist_df['event'], y=hist_df['gw_average'],
                    name='GW Average', line=dict(color='#ff1751', width=2, dash='dash'),
                ))
                fig.add_trace(go.Scatter(
                    x=hist_df['event'], y=hist_df['total_points'],
                    name='Cumulative Pts', yaxis='y2',
                    line=dict(color='#00ff85', width=2),
                ))
                fig.update_layout(
                    title="Points per Gameweek vs Average",
                    xaxis_title="Gameweek",
                    yaxis=dict(title="GW Points"),
                    yaxis2=dict(title="Cumulative Points", overlaying='y', side='right'),
                    legend=dict(orientation='h'),
                    margin=dict(l=40, r=40, t=40, b=40),
                )
                st.plotly_chart(fig, width="stretch")

                # Rank chart
                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(
                    x=hist_df['event'], y=hist_df['overall_rank'],
                    fill='tozeroy', line=dict(color='#38003c'), name='Overall Rank',
                ))
                fig2.update_layout(
                    title="Overall Rank Over Season (lower = better)",
                    xaxis_title="Gameweek",
                    yaxis=dict(title="Rank", autorange='reversed'),
                    margin=dict(l=40, r=40, t=40, b=40),
                )
                st.plotly_chart(fig2, width="stretch")

                # --- Position Efficiency Breakdown ---
                st.markdown("---")
                st.subheader("Points by Position — Current Squad")
                if not my_squad.empty:
                    pos_pts = (
                        my_squad.groupby('pos')['total_points']
                        .sum()
                        .reset_index()
                        .sort_values('total_points', ascending=False)
                    )
                    pos_count = my_squad.groupby('pos')['total_points'].count().reset_index()
                    pos_count.columns = ['pos', 'n_players']
                    pos_pts = pos_pts.merge(pos_count, on='pos')
                    pos_pts['pts_per_player'] = (pos_pts['total_points'] / pos_pts['n_players']).round(1)

                    fig_pos = go.Figure()
                    fig_pos.add_trace(go.Bar(
                        x=pos_pts['pos'], y=pos_pts['total_points'],
                        marker_color='#38003c', name='Total Points',
                        text=pos_pts['pts_per_player'].apply(lambda v: f"{v} pts/player"),
                        textposition='outside',
                    ))
                    fig_pos.update_layout(
                        title="Season Points by Position (current squad composition)",
                        xaxis_title="Position", yaxis_title="Total Points",
                        margin=dict(l=40, r=40, t=40, b=40),
                    )
                    st.plotly_chart(fig_pos, width="stretch")
                    st.caption("Shows the season-to-date totals for your current squad players grouped by position.")
                else:
                    st.info("Load your squad (Manager ID) to see position breakdown.")

                # GW breakdown table
                display_cols = ['event', 'points', 'gw_average', 'total_points', 'overall_rank', 'bank', 'value', 'event_transfers', 'event_transfers_cost']
                available = [c for c in display_cols if c in hist_df.columns]
                rename = {
                    'event': 'GW', 'points': 'Pts', 'gw_average': 'GW Avg',
                    'total_points': 'Total Pts', 'overall_rank': 'Rank',
                    'bank': 'Bank (0.1m)', 'value': 'Value (0.1m)',
                    'event_transfers': 'Transfers', 'event_transfers_cost': 'Hit Cost',
                }
                st.subheader("Full GW Breakdown")
                st.dataframe(hist_df[available].rename(columns=rename), width="stretch", hide_index=True)
                st.download_button(
                    "Download History CSV",
                    df_to_csv(hist_df[available].rename(columns=rename)),
                    file_name="gw_history.csv", mime="text/csv",
                )

                # --- Hit Cost Impact Chart ---
                if 'event_transfers_cost' in hist_df.columns:
                    st.markdown("---")
                    st.subheader("Transfer Hit Cost Analysis")
                    hist_df['cumulative_hit_cost'] = hist_df['event_transfers_cost'].cumsum()
                    total_hit_pts = int(hist_df['event_transfers_cost'].sum())
                    hc1, hc2 = st.columns(2)
                    hc1.metric("Total Hit Cost (pts)", total_hit_pts)
                    hc2.metric("Hits Taken", int((hist_df['event_transfers_cost'] > 0).sum()))
                    fig_hits = go.Figure()
                    fig_hits.add_trace(go.Bar(
                        x=hist_df['event'], y=hist_df['event_transfers_cost'],
                        name='Hit Cost per GW', marker_color='#ff1751', opacity=0.85,
                    ))
                    fig_hits.add_trace(go.Scatter(
                        x=hist_df['event'], y=hist_df['cumulative_hit_cost'],
                        name='Cumulative Hit Cost', yaxis='y2',
                        line=dict(color='#38003c', width=2),
                    ))
                    fig_hits.update_layout(
                        title="Transfer Hit Costs Over Season",
                        xaxis_title="Gameweek",
                        yaxis=dict(title="Hit Cost (pts)"),
                        yaxis2=dict(title="Cumulative Cost", overlaying='y', side='right'),
                        legend=dict(orientation='h'),
                        margin=dict(l=40, r=40, t=40, b=40),
                    )
                    st.plotly_chart(fig_hits, width="stretch")

                # Transfer history
                st.markdown("---")
                st.subheader("Transfer History")
                try:
                    transfers = get_transfer_history(my_id)
                    if transfers:
                        tf_df = pd.DataFrame(transfers)
                        id_to_name = dict(zip(players['id'], players['web_name']))
                        id_to_price = dict(zip(players['id'], players['price']))
                        tf_df['Player In'] = tf_df['element_in'].map(id_to_name)
                        tf_df['Player Out'] = tf_df['element_out'].map(id_to_name)
                        tf_df['Cost In (£m)'] = tf_df['element_in_cost'].apply(lambda x: round(x / 10, 1))
                        tf_df['Cost Out (£m)'] = tf_df['element_out_cost'].apply(lambda x: round(x / 10, 1))
                        tf_df['Current Val (£m)'] = tf_df['element_in'].map(id_to_price)
                        tf_df['Gain (£m)'] = (tf_df['Current Val (£m)'] - tf_df['Cost In (£m)']).round(1)
                        show_cols = ['event', 'Player In', 'Cost In (£m)', 'Current Val (£m)', 'Gain (£m)', 'Player Out', 'Cost Out (£m)']
                        available_tf = [c for c in show_cols if c in tf_df.columns]
                        st.dataframe(
                            tf_df[available_tf].rename(columns={'event': 'GW'}).sort_values('GW', ascending=False),
                            use_container_width=True, hide_index=True,
                        )
                        st.download_button(
                            "Download Transfer History CSV",
                            df_to_csv(tf_df[available_tf].rename(columns={'event': 'GW'})),
                            file_name="transfer_history.csv", mime="text/csv",
                        )
                    else:
                        st.info("No transfer history found.")
                except requests.RequestException:
                    st.warning("Could not load transfer history.")
            else:
                st.info("No gameweek history found for this manager.")
        except requests.RequestException:
            st.error("Could not load manager history. Check your Manager ID.")
    else:
        st.info("Enter your Manager ID in the sidebar.")

# ── TAB 3: GLOBAL SCOUT ─────────────────────────────────────────────────────
with tabs[3]:
    st.header("Global Player Scout")
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        min_p = st.slider("Min Price (£m)", 3.5, 14.5, 3.5, step=0.5, key="scout_min_p",
                          help="Lower bound for player price filter.")
    with s2:
        max_p = st.slider("Max Price (£m)", 4.0, 15.0, 15.0, step=0.5, key="scout_p",
                          help="Upper bound for player price filter.")
    with s3:
        po_filt = st.multiselect(
            "Positions",
            options=list(pos_map.values()),
            default=list(pos_map.values()),
            key="scout_pos",
            help="Filter by FPL position.",
        )
    with s4:
        t_filt = st.multiselect(
            "Teams",
            options=sorted(list(team_map.values())),
            default=sorted(list(team_map.values())),
            key="scout_team",
            help="Filter by team.",
        )

    scout_df = players[
        (players['price'] >= min_p) &
        (players['price'] <= max_p) &
        (players['pos'].isin(po_filt)) &
        (players['team_name'].isin(t_filt))
    ].copy()

    _sort_opts = {
        'Total Points': 'total_points', 'xPts (next GW)': 'xpts', 'Form': 'form',
        'ICT Index': 'ict_index', 'PPM': 'ppm', 'Net Transfers (GW)': 'net_transfers',
        'Form Trend': 'form_trend',
    }
    _net_avail = 'net_transfers' in scout_df.columns
    _sort_keys = [k for k in _sort_opts if k != 'Net Transfers (GW)' or _net_avail]
    scout_sort = st.selectbox("Sort by", _sort_keys, index=0, key="scout_sort")
    scout_cols = [
        'web_name', 'team_name', 'pos', 'price',
        'xpts', 'proj_pts', 'play_prob',
        'ppm', 'total_points', 'form', 'form_trend',
        'ict_index', 'expected_goals', 'expected_assists', 'expected_goal_involvements',
        'expected_goals_conceded', 'selected_by_percent',
    ]
    if _net_avail:
        scout_cols.insert(-1, 'net_transfers')
    # Add projections for richer scouting
    scout_df = add_projection_columns(scout_df, horizon_gws=3)
    sorted_scout = scout_df.sort_values(_sort_opts[scout_sort], ascending=False)
    st.dataframe(get_display_df(sorted_scout, scout_cols), width="stretch", hide_index=True)
    st.download_button(
        "Download Scout CSV",
        df_to_csv(get_display_df(sorted_scout, scout_cols)),
        file_name="player_scout.csv", mime="text/csv",
    )

    # --- Compare drawer ---
    st.markdown("---")
    st.subheader("Quick Compare")
    st.caption("Pick multiple players to compare key stats side-by-side.")
    _compare_pool = sorted_scout.head(200).copy()
    _name_to_id = dict(zip(_compare_pool["web_name"], _compare_pool["id"]))
    _compare_names = st.multiselect(
        "Players to compare",
        options=list(_name_to_id.keys()),
        default=[],
        key="scout_compare",
        help="Uses the current filtered/sorted list (top 200) as the selection pool.",
    )
    if _compare_names:
        _cmp = players[players["id"].isin([_name_to_id[n] for n in _compare_names])].copy()
        _cmp_cols = [
            "web_name", "team_name", "pos", "price",
            "proj_pts", "play_prob", "xpts",
            "ppm", "form",
            "ict_index", "expected_goals", "expected_assists", "expected_goal_involvements",
            "expected_goals_conceded",
            "total_points", "selected_by_percent", "chance_of_playing_next_round",
        ]
        st.dataframe(get_display_df(_cmp, _cmp_cols), width="stretch", hide_index=True)
        st.download_button(
            "Download Compare CSV",
            df_to_csv(get_display_df(_cmp, _cmp_cols)),
            file_name="compare_players.csv",
            mime="text/csv",
        )

    # --- Value vs Points Scatter ---
    st.markdown("---")
    st.subheader("Value vs Points — Bubble Chart")
    st.caption("Bubble size = ownership %. Players in the top-left are high value for money.")
    scatter_df = scout_df.dropna(subset=['price', 'total_points', 'selected_by_percent'])
    fig_scatter = go.Figure()
    for pos_name, color in [('GKP', '#38003c'), ('DEF', '#00753e'), ('MID', '#01fc7a'), ('FWD', '#ff1751')]:
        subset = scatter_df[scatter_df['pos'] == pos_name]
        if subset.empty:
            continue
        fig_scatter.add_trace(go.Scatter(
            x=subset['price'],
            y=subset['total_points'],
            mode='markers',
            name=pos_name,
            marker=dict(
                size=subset['selected_by_percent'].clip(lower=1) * 1.5,
                color=color,
                opacity=0.7,
                sizemode='area',
            ),
            text=subset['web_name'] + '<br>Own: ' + subset['selected_by_percent'].astype(str) + '%',
            hovertemplate='%{text}<br>£%{x}m | %{y} pts<extra></extra>',
        ))
    fig_scatter.update_layout(
        xaxis_title="Price (£m)", yaxis_title="Total Points",
        legend=dict(orientation='h'), margin=dict(l=40, r=40, t=20, b=40),
    )
    st.plotly_chart(fig_scatter, width="stretch")

    # --- Differential Finder ---
    st.markdown("---")
    st.subheader("Differential Finder")
    st.caption(f"High ICT players owned by fewer than {DIFF_MAX_OWNERSHIP}% of managers. Sorted by differential score (ICT / ownership).")
    diff_max_own = st.slider("Max Ownership %", 2.0, 20.0, float(DIFF_MAX_OWNERSHIP), step=1.0, key="diff_own")
    diffs = add_projection_columns(players[players['selected_by_percent'] <= diff_max_own].copy(), horizon_gws=3)
    diffs['diff_score'] = (diffs['ict_index'] / diffs['selected_by_percent'].clip(lower=0.1)).round(1)
    diff_cols = [
        'web_name', 'team_name', 'pos', 'price',
        'selected_by_percent', 'xpts', 'proj_pts', 'play_prob',
        'form', 'ict_index', 'expected_goals', 'expected_goal_involvements',
        'diff_score',
    ]
    st.dataframe(
        get_display_df(diffs.nlargest(20, 'diff_score'), diff_cols),
        use_container_width=True, hide_index=True,
    )

    # --- Hot & Cold Form ---
    st.markdown("---")
    st.subheader("Hot & Cold Players")
    st.caption("Form trend = recent form minus season points-per-game. Positive = in form, negative = cold.")
    hc_cols = ['web_name', 'team_name', 'pos', 'price', 'form', 'season_ppg', 'form_trend', 'xpts', 'selected_by_percent']
    hc1, hc2 = st.columns(2)
    with hc1:
        st.markdown("**Hottest Players (form above season avg)**")
        hot_df = scout_df[scout_df['form_trend'] > 0].nlargest(10, 'form_trend')
        st.dataframe(get_display_df(hot_df, hc_cols), width="stretch", hide_index=True)
    with hc2:
        st.markdown("**Coldest Players (form below season avg)**")
        cold_df = scout_df[scout_df['form_trend'] < 0].nsmallest(10, 'form_trend')
        st.dataframe(get_display_df(cold_df, hc_cols), width="stretch", hide_index=True)

    # --- Template Comparison ---
    st.markdown("---")
    st.subheader("FPL Template Comparison")
    st.caption("Top 30 most-owned players globally vs your squad.")
    template = players.nlargest(30, 'selected_by_percent')[
        ['web_name', 'team_name', 'pos', 'price', 'selected_by_percent', 'xpts', 'total_points', 'form']
    ].copy()
    if not my_squad.empty:
        template['In Your Squad'] = template['web_name'].isin(my_squad['web_name']).map({True: 'Yes', False: 'No'})
        owned_count = template['In Your Squad'].eq('Yes').sum()
        st.caption(f"You own {owned_count}/30 template players.")
    st.dataframe(
        get_display_df(template, ['web_name', 'team_name', 'pos', 'price', 'selected_by_percent', 'xpts', 'total_points', 'form']),
        use_container_width=True, hide_index=True,
    )

# ── TAB 4: PRICE CHANGES ────────────────────────────────────────────────────
with tabs[4]:
    st.header("Price Change Tracker")
    st.caption("Based on `cost_change_event` (this GW) and `cost_change_start` (vs. season start).")
    pc1, pc2 = st.columns(2)
    rising_cols = ['web_name', 'team_name', 'pos', 'price', 'cost_change_event', 'form', 'selected_by_percent']
    with pc1:
        st.subheader("Rising — This GW")
        rising = players[players['cost_change_event'] > 0].sort_values('cost_change_event', ascending=False)
        st.dataframe(get_display_df(rising, rising_cols), width="stretch", hide_index=True)
    with pc2:
        st.subheader("Falling — This GW")
        falling = players[players['cost_change_event'] < 0].sort_values('cost_change_event')
        st.dataframe(get_display_df(falling, rising_cols), width="stretch", hide_index=True)

    st.markdown("---")
    st.subheader("Biggest Movers Since Season Start")
    movers = players.copy()
    movers['abs_change'] = movers['cost_change_start'].abs()
    movers = movers.sort_values('abs_change', ascending=False).head(20)
    mover_cols = ['web_name', 'team_name', 'pos', 'price', 'cost_change_start', 'form', 'selected_by_percent']
    st.dataframe(get_display_df(movers, mover_cols), width="stretch", hide_index=True)

    # --- Price Rise Predictor ---
    st.markdown("---")
    st.subheader("Price Rise Predictor")
    st.caption(
        "Players with high/rising ownership but no price change yet this GW. "
        "Heavy net transfers-in pushes price up — these are candidates for an imminent rise."
    )
    # Proxy: highly owned players who haven't risen this GW, sorted by ownership %
    no_change = players[(players['cost_change_event'] == 0) & (players['selected_by_percent'] > 5)].copy()
    # Use transfers_in_event / transfers_out_event if available as a signal
    if 'transfers_in_event' in no_change.columns and 'transfers_out_event' in no_change.columns:
        no_change['net_transfers'] = no_change['transfers_in_event'] - no_change['transfers_out_event']
        rise_candidates = no_change.sort_values('net_transfers', ascending=False).head(20)
        rise_cols = ['web_name', 'team_name', 'pos', 'price', 'selected_by_percent', 'net_transfers', 'form']
    else:
        rise_candidates = no_change.sort_values('selected_by_percent', ascending=False).head(20)
        rise_cols = ['web_name', 'team_name', 'pos', 'price', 'selected_by_percent', 'form']
    st.dataframe(get_display_df(rise_candidates, rise_cols), width="stretch", hide_index=True)

# ── TAB 5: TICKER ───────────────────────────────────────────────────────────
with tabs[5]:
    st.header("Fixture Difficulty Ticker")

    # --- DGW / Blank Early Warning Panel ---
    st.subheader("DGW / Blank Early Warning — Next 10 GWs")
    _base_gw = (curr_gw_id or 0) + 1
    _all_team_ids = set(team_map.keys())
    _warning_rows = []
    for _gw in range(_base_gw, _base_gw + 10):
        _gw_fixtures = [f for f in fixtures_raw if f['event'] == _gw]
        if not _gw_fixtures:
            break
        _teams_in_gw = pd.Series(
            [f['team_h'] for f in _gw_fixtures] + [f['team_a'] for f in _gw_fixtures]
        ).value_counts()
        _dgw = [team_map[t] for t in _teams_in_gw[_teams_in_gw > 1].index]
        _blank = [team_map[t] for t in _all_team_ids if t not in _teams_in_gw.index]
        _warning_rows.append({
            'GW': _gw,
            'DGW Teams': ', '.join(sorted(_dgw)) if _dgw else '—',
            '# DGW': len(_dgw),
            'Blank Teams': ', '.join(sorted(_blank)) if _blank else '—',
            '# Blank': len(_blank),
        })
    if _warning_rows:
        _warn_df = pd.DataFrame(_warning_rows)
        st.dataframe(_warn_df, width="stretch", hide_index=True)
        _next_dgw = next((_r for _r in _warning_rows if _r['# DGW'] > 0), None)
        _next_blank = next((_r for _r in _warning_rows if _r['# Blank'] > 0), None)
        if _next_dgw:
            st.info(f"Next DGW: GW{_next_dgw['GW']} — {_next_dgw['DGW Teams']}")
        if _next_blank:
            st.warning(f"Next Blank GW: GW{_next_blank['GW']} — {_next_blank['Blank Teams']}")
    st.markdown("---")

    t_ctrl1, t_ctrl2, t_ctrl3 = st.columns([1, 1, 2])
    with t_ctrl1:
        sort_by_difficulty = st.toggle("Sort by easiest run", value=False, help="Sort teams by total difficulty score.")
    with t_ctrl2:
        show_fixture_map = st.toggle("Show fixture map", value=True, help="Show a compact team×GW fixture grid.")
    with t_ctrl3:
        dgw_focus = st.toggle("DGW focus", value=False, help="Highlight DGW teams and surface DGW-targeted player filters.")

    my_team_names = set(my_squad['team_name'].tolist()) if not my_squad.empty else set()
    gw_cols = [f"GW+{i}" for i in range(1, fixture_lookahead + 1)]
    ticker_data = []
    for t_id, t_name in team_map.items():
        upcoming = get_upcoming_fixtures(t_id, fixtures_raw, data, num_gws=fixture_lookahead)
        score = fixture_difficulty_score(upcoming)
        ticker_data.append([t_name] + upcoming + [score])

    df_tick = pd.DataFrame(ticker_data, columns=["Team"] + gw_cols + ["Run Score"])
    if sort_by_difficulty:
        df_tick = df_tick.sort_values("Run Score")

    fixture_subset = [c for c in gw_cols if c in df_tick.columns]
    styled = (
        df_tick.drop(columns=["Run Score"])
        .style
        .map(style_ticker, subset=fixture_subset)
        .apply(style_ticker_row, my_team_names=my_team_names, axis=1)
    )
    st.dataframe(styled, width="stretch", hide_index=True)
    if my_team_names:
        st.caption("Bold green border = team in your squad.")
    if sort_by_difficulty:
        st.caption("Run Score = sum of difficulty ratings (lower = easier). Blanks=3, DGWs=1.5.")

    # --- Fixture Map + DGW/Blank helpers ---
    if show_fixture_map:
        st.markdown("---")
        st.subheader("Fixture Map — Next GWs")
        st.caption("Cells show opponent difficulty. DGW is purple, blanks are grey. Use DGW focus to filter players.")

        # Re-use df_tick without Run Score; show the grid
        grid = df_tick.drop(columns=["Run Score"]).copy()
        st.dataframe(
            grid.style.map(style_ticker, subset=gw_cols),
            use_container_width=True,
            hide_index=True,
        )

    if dgw_focus and next_gw:
        st.markdown("---")
        st.subheader("DGW / Blank Targeting")

        _s = gw_status_for(next_gw["id"])
        _dgw_team_ids = [int(x) for x in _s["dgw_team_ids"]]
        _active = _s["active_team_ids"]
        _blank_team_ids = sorted([int(t) for t in team_map.keys() if int(t) not in _active]) if _active else []

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**DGW teams (next GW)**")
            st.write(_team_list(_dgw_team_ids))
        with c2:
            st.markdown("**Blank teams (next GW)**")
            st.write(_team_list(_blank_team_ids))

        filt1, filt2, filt3 = st.columns([1, 1, 2])
        with filt1:
            only_dgw = st.checkbox("Only DGW players", value=True, help="Show only players whose team has a DGW next GW.")
        with filt2:
            hide_blanks = st.checkbox("Hide blankers", value=True, help="Exclude players whose team has no fixture next GW.")
        with filt3:
            max_price = st.slider("Max price (£m)", 3.5, 15.0, 15.0, 0.5, help="Budget filter for targets.")

        _pool = players.copy()
        if only_dgw:
            _pool = _pool[_pool["team"].isin(_dgw_team_ids)]
        if hide_blanks and _active:
            _pool = _pool[_pool["team"].isin(list(_active))]
        _pool = _pool[_pool["price"] <= max_price]

        # Add projections for a short horizon (same as fixture_lookahead)
        _pool = add_projection_columns(_pool, horizon_gws=min(5, max(2, int(fixture_lookahead))))
        _cols = [
            "web_name",
            "team_name",
            "pos",
            "price",
            "proj_pts",
            "play_prob",
            "xpts",
            "form",
            "ppm",
            "ict_index",
            "selected_by_percent",
        ]
        st.dataframe(
            get_display_df(_pool.sort_values("proj_pts", ascending=False).head(40), _cols),
            use_container_width=True,
            hide_index=True,
        )

# ── TAB 6: PLAYER VS ────────────────────────────────────────────────────────
with tabs[6]:
    st.header("Player VS Radar")
    search_mode = st.toggle("Search by player name", value=False)

    if search_mode:
        # Add team filters to avoid scrolling huge lists.
        v1, v2 = st.columns(2)
        with v1:
            tm1 = st.selectbox("Team 1", sorted(teams['name'].unique()), key="vs_tm1_search")
            p1 = st.selectbox(
                "Player 1",
                sorted(players[players['team_name'] == tm1]['web_name'].unique()),
                key="vs_p1_search",
            )
        with v2:
            tm2 = st.selectbox("Team 2", sorted(teams['name'].unique()), key="vs_tm2_search", index=1)
            p2 = st.selectbox(
                "Player 2",
                sorted(players[players['team_name'] == tm2]['web_name'].unique()),
                key="vs_p2_search",
            )
    else:
        v1, v2 = st.columns(2)
        with v1:
            tm1 = st.selectbox("Team 1", sorted(teams['name'].unique()), key="v1_tm")
            p1 = st.selectbox("Player 1", sorted(players[players['team_name'] == tm1]['web_name']), key="v1_p")
        with v2:
            tm2 = st.selectbox("Team 2", sorted(teams['name'].unique()), key="v2_tm", index=1)
            p2 = st.selectbox("Player 2", sorted(players[players['team_name'] == tm2]['web_name']), key="v2_p")

    def make_rad(name, team):
        matches = players[(players['web_name'] == name) & (players['team_name'] == team)]
        if matches.empty:
            return [0] * len(RADAR_METRICS)
        return [matches.iloc[0][m] for m in RADAR_METRICS]

    if p1 and p2 and tm1 and tm2:
        fig_v = go.Figure()
        fig_v.add_trace(go.Scatterpolar(r=make_rad(p1, tm1), theta=RADAR_METRICS, fill='toself', name=p1, line_color='#38003c'))
        fig_v.add_trace(go.Scatterpolar(r=make_rad(p2, tm2), theta=RADAR_METRICS, fill='toself', name=p2, line_color='#00ff85'))
        fig_v.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, players[RADAR_METRICS].max().max()])),
            showlegend=True, margin=dict(l=40, r=40, t=40, b=40),
        )
        st.plotly_chart(fig_v, width="stretch")

        st.subheader("Stats Comparison")
        compare_cols = [
            'web_name', 'team_name', 'pos', 'price',
            'proj_pts', 'play_prob', 'xpts',
            'form',
            'expected_goals', 'expected_assists', 'expected_goal_involvements', 'expected_goals_conceded',
            'ict_index', 'total_points', 'selected_by_percent',
        ]
        p1_row = players[(players['web_name'] == p1) & (players['team_name'] == tm1)]
        p2_row = players[(players['web_name'] == p2) & (players['team_name'] == tm2)]
        st.dataframe(get_display_df(pd.concat([p1_row, p2_row]), compare_cols), width="stretch", hide_index=True)

        # GW-by-GW points chart
        st.subheader("GW Points — This Season")
        gw_fig = go.Figure()
        for player_name, team_name, color in [(p1, tm1, '#38003c'), (p2, tm2, '#00ff85')]:
            p_row = players[(players['web_name'] == player_name) & (players['team_name'] == team_name)]
            if not p_row.empty:
                player_id = int(p_row.iloc[0]['id'])
                try:
                    p_history = get_player_history(player_id)
                    gw_data = pd.DataFrame(p_history.get('history', []))
                    if not gw_data.empty:
                        gw_fig.add_trace(go.Scatter(
                            x=gw_data['round'], y=gw_data['total_points'],
                            name=player_name, line=dict(color=color, width=2),
                            mode='lines+markers',
                        ))
                except requests.RequestException:
                    pass
        gw_fig.update_layout(
            xaxis_title="Gameweek", yaxis_title="Points",
            legend=dict(orientation='h'), margin=dict(l=40, r=40, t=20, b=40),
        )
        st.plotly_chart(gw_fig, width="stretch")

# ── TAB 7: MINI-LEAGUE ──────────────────────────────────────────────────────
with tabs[7]:
    st.header("Mini-League Standings")
    league_type = st.radio("League Type", ["Classic", "Head-to-Head"], horizontal=True)
    league_id = st.text_input(
        "Enter League ID",
        value=str(st.query_params.get("league", _local_settings.get("league_id", ""))),
        key="league_input",
        help="Classic league ID. Saved locally for next time.",
    )
    if league_id:
        st.query_params["league"] = league_id
        _local_settings["league_id"] = league_id

    if league_id:
        try:
            if league_type == "Classic":
                league_data = get_league_standings(league_id)
                results = league_data.get('standings', {}).get('results', [])
                league_name = league_data.get('league', {}).get('name', 'League')
                if results:
                    league_df = pd.DataFrame(results)
                    col_map = {
                        'rank': 'Rank', 'entry_name': 'Team Name', 'player_name': 'Manager',
                        'event_total': 'GW Score', 'total': 'Total Pts', 'last_rank': 'Last Rank',
                    }
                    available = [c for c in col_map if c in league_df.columns]
                    league_display = league_df[available].rename(columns=col_map)
                    if 'last_rank' in league_df.columns and 'rank' in league_df.columns:
                        league_display['Movement'] = (league_df['last_rank'] - league_df['rank']).apply(
                            lambda x: f"+{x}" if x > 0 else str(x)
                        )
                    st.subheader(league_name)
                    st.dataframe(league_display, width="stretch", hide_index=True)
                    st.download_button("Download Standings CSV", df_to_csv(league_display),
                                       file_name=f"{league_name}_standings.csv", mime="text/csv")

                    # --- Mini-league target mode (simplified) ---
                    st.markdown("---")
                    st.subheader("Target Mode (top rivals)")
                    st.caption("Pick a few rivals from this league to compare squads and spot differentials.")
                    try:
                        _name_to_entry = dict(zip(league_df["entry_name"], league_df["entry"]))
                        _choices = league_df["entry_name"].head(20).tolist()
                        _picked = st.multiselect(
                            "Rivals to target (max 3)",
                            options=_choices,
                            default=_choices[:1],
                            help="We will fetch their current GW picks and compare to your squad.",
                            max_selections=3,
                            key="league_target_pick",
                        )
                        if _picked and my_id and curr_gw_event:
                            for tname in _picked:
                                tid = str(_name_to_entry.get(tname))
                                rp = fetch_squad_picks(tid, curr_gw_id)
                                if not rp:
                                    st.warning(f"Could not load picks for {tname}.")
                                    continue
                                r_ids = set([p["element"] for p in rp])
                                shared = players[players["id"].isin(set(my_player_ids) & r_ids)].copy()
                                mine = players[players["id"].isin(set(my_player_ids) - r_ids)].copy()
                                theirs = players[players["id"].isin(r_ids - set(my_player_ids))].copy()
                                st.markdown(f"**{tname}**")
                                c1, c2, c3 = st.columns(3)
                                c1.metric("Shared", int(len(shared)))
                                c2.metric("Your diffs", int(len(mine)))
                                c3.metric("Their diffs", int(len(theirs)))
                                st.dataframe(get_display_df(theirs, ["web_name", "team_name", "pos", "price", "proj_pts", "confidence_tier", "variance_flags", "selected_by_percent"]), width="stretch", hide_index=True)
                        elif _picked and (not my_id or not curr_gw_event):
                            st.info("Enter your Manager ID and ensure a current GW is detected to compare squads.")
                    except Exception:
                        st.info("Target mode unavailable for this league data.")

                    # --- Mini-League Form Table (last 5 GWs) ---
                    st.markdown("---")
                    st.subheader("Form Table — Last 5 Gameweeks")
                    st.caption("Fetches history for each manager. Limited to 20 managers.")
                    if st.button("Load form data", key="load_form"):
                        manager_entries = league_df[['entry', 'entry_name']].head(20).to_dict('records')
                        form_rows = []
                        prog = st.progress(0, text="Fetching manager histories…")
                        for i, mgr in enumerate(manager_entries):
                            try:
                                h = get_manager_history(str(mgr['entry']))
                                gws = h.get('current', [])
                                last5 = sorted(gws, key=lambda x: x['event'])[-5:]
                                row = {'Team': mgr['entry_name']}
                                for gw_entry in last5:
                                    row[f"GW{gw_entry['event']}"] = gw_entry['points']
                                form_rows.append(row)
                            except requests.RequestException:
                                pass
                            prog.progress((i + 1) / len(manager_entries))
                        prog.empty()
                        if form_rows:
                            form_df = pd.DataFrame(form_rows).set_index('Team')
                            st.dataframe(form_df, width="stretch")
                        else:
                            st.warning("Could not load form data.")
                else:
                    st.info("No standings data found.")
            else:
                h2h_data = get_h2h_standings(league_id)
                results = h2h_data.get('standings', {}).get('results', [])
                league_name = h2h_data.get('league', {}).get('name', 'H2H League')
                if results:
                    h2h_df = pd.DataFrame(results)
                    h2h_col_map = {
                        'rank': 'Rank', 'entry_name': 'Team Name', 'player_name': 'Manager',
                        'matches_won': 'W', 'matches_drawn': 'D', 'matches_lost': 'L',
                        'points_for': 'Pts For', 'total': 'H2H Pts',
                    }
                    available = [c for c in h2h_col_map if c in h2h_df.columns]
                    h2h_display = h2h_df[available].rename(columns=h2h_col_map)
                    st.subheader(league_name)
                    st.dataframe(h2h_display, width="stretch", hide_index=True)
                    st.download_button("Download H2H Standings CSV", df_to_csv(h2h_display),
                                       file_name=f"{league_name}_h2h.csv", mime="text/csv")
                else:
                    st.info("No standings data found.")
        except requests.RequestException:
            st.error("League not found or is private. Check the League ID.")

# ── TAB 8: RIVALS ───────────────────────────────────────────────────────────
with tabs[8]:
    st.header("Rival Deep-Dive")
    rival_id = st.text_input(
        "Enter Rival Manager ID",
        value=str(st.query_params.get("rival", _local_settings.get("rival_id", ""))),
        key="riv_input",
        help="Optional. Compare your squad to another manager by entry ID.",
    )
    if rival_id:
        st.query_params["rival"] = rival_id
        _local_settings["rival_id"] = rival_id

    if my_id and rival_id and curr_gw_event:
        picks = fetch_squad_picks(rival_id, curr_gw_id)
        if picks is None:
            st.error("Rival ID not found or request failed.")
        else:
            riv_ids = [p['element'] for p in picks]
            my_set, riv_set = set(my_player_ids), set(riv_ids)
            riv_cols = [
                'web_name', 'team_name', 'pos', 'price',
                'proj_pts', 'play_prob', 'xpts',
                'form',
                'expected_goals', 'expected_assists', 'expected_goal_involvements', 'expected_goals_conceded',
                'ict_index', 'total_points',
                'selected_by_percent',
            ]

            st.subheader("Shield (Shared Assets)")
            st.dataframe(get_display_df(players[players['id'].isin(my_set & riv_set)], riv_cols), width="stretch", hide_index=True)
            st.subheader("Your Sword (Differentials)")
            st.dataframe(get_display_df(players[players['id'].isin(my_set - riv_set)], riv_cols), width="stretch", hide_index=True)
            st.subheader("Danger (Rival Differentials)")
            st.dataframe(get_display_df(players[players['id'].isin(riv_set - my_set)], riv_cols), width="stretch", hide_index=True)

            # --- Rival swing analysis (simplified) ---
            st.markdown("---")
            st.subheader("Captaincy swing — you vs rival")
            st.caption("Uses short-horizon projections as a rough swing estimate (not guaranteed).")
            _my_proj = add_projection_columns(players[players["id"].isin(my_player_ids)].copy(), horizon_gws=2)
            _riv_proj = add_projection_columns(players[players["id"].isin(list(riv_ids))].copy(), horizon_gws=2)
            _my_cap = _my_proj.sort_values(["proj_pts", "play_prob"], ascending=[False, False]).head(1)
            _riv_cap = _riv_proj.sort_values(["proj_pts", "play_prob"], ascending=[False, False]).head(1)
            if not _my_cap.empty and not _riv_cap.empty:
                my_cap_name = _my_cap.iloc[0]["web_name"]
                riv_cap_name = _riv_cap.iloc[0]["web_name"]
                my_cap_pts = float(_my_cap.iloc[0]["proj_pts"])
                riv_cap_pts = float(_riv_cap.iloc[0]["proj_pts"])
                # Approx swing if you captain your pick and rival captains theirs: +2*mine - 2*rival
                swing = round(2 * my_cap_pts - 2 * riv_cap_pts, 1)
                s1, s2, s3 = st.columns(3)
                s1.metric("Your projected captain", f"{my_cap_name} ({my_cap_pts:.1f})")
                s2.metric("Rival projected captain", f"{riv_cap_name} ({riv_cap_pts:.1f})")
                s3.metric("Est. captain swing", swing, help="Approx: 2×(your cap proj − rival cap proj).")
            else:
                st.info("Could not compute captain swing (missing projection inputs).")

            # --- Rival Rank History ---
            st.markdown("---")
            st.subheader("Rank History — You vs Rival")
            try:
                my_hist = get_manager_history(my_id)
                riv_hist = get_manager_history(rival_id)
                my_gws = pd.DataFrame(my_hist.get('current', []))[['event', 'overall_rank']]
                riv_gws = pd.DataFrame(riv_hist.get('current', []))[['event', 'overall_rank']]
                fig_rank = go.Figure()
                fig_rank.add_trace(go.Scatter(
                    x=my_gws['event'], y=my_gws['overall_rank'],
                    name='Your Rank', line=dict(color='#00ff85', width=2),
                ))
                fig_rank.add_trace(go.Scatter(
                    x=riv_gws['event'], y=riv_gws['overall_rank'],
                    name='Rival Rank', line=dict(color='#ff1751', width=2, dash='dash'),
                ))
                fig_rank.update_layout(
                    title="Overall Rank — You vs Rival (lower = better)",
                    xaxis_title="Gameweek",
                    yaxis=dict(title="Rank", autorange='reversed'),
                    legend=dict(orientation='h'),
                    margin=dict(l=40, r=40, t=40, b=40),
                )
                st.plotly_chart(fig_rank, width="stretch")
            except (requests.RequestException, KeyError):
                st.warning("Could not load rank history for one or both managers.")

    elif rival_id and not curr_gw_event:
        st.warning("No current gameweek found.")
    elif not my_id:
        st.info("Enter your Manager ID in the sidebar to compare squads.")

# ── TAB 9: TRANSFERS ────────────────────────────────────────────────────────
with tabs[9]:
    st.header("Transfer Optimizer")
    if not my_squad.empty:
        my_squad['efficiency'] = (my_squad['form'] + (my_squad['total_points'] / my_squad['price'])).round(1)
        num_ft = st.radio(
            "Free Transfers Available",
            options=[0, 1, 2, 3, 4, 5, "Wildcard"],
            horizontal=True,
            help="FPL allows you to bank free transfers up to 5. Used here to decide how many 'drop candidates' to surface.",
        )
        n_transfers = 5 if num_ft == "Wildcard" else int(num_ft)

        # Rotation risk in squad: flag players averaging < 55 min
        _rot_risk_players = my_squad[my_squad['rotation_risk'] == 'Low mins']['web_name'].tolist()
        if _rot_risk_players:
            st.warning(f"Rotation risk (low avg mins): {', '.join(_rot_risk_players)}")

        candidates = my_squad.sort_values('efficiency').head(n_transfers)
        st.subheader("Drop Candidates")
        drop_cols = [
            'web_name', 'team_name', 'pos', 'price',
            'proj_pts', 'play_prob', 'xpts',
            'form',
            'expected_goals', 'expected_assists', 'expected_goal_involvements', 'expected_goals_conceded',
            'ppm', 'efficiency',
            'avg_minutes', 'rotation_risk', 'selected_by_percent',
        ]
        st.dataframe(get_display_df(candidates, drop_cols), width="stretch", hide_index=True)

        st.subheader("Recommended Replacements (per candidate)")
        for _, worst in candidates.iterrows():
            with st.expander(f"Replace {worst['web_name']} (£{worst['price']}m | Eff: {worst['efficiency']})"):
                bud = worst['price'] + (2.0 if num_ft == "Wildcard" else TRANSFER_BUDGET_BUFFER)
                targets = players[
                    (players['pos'] == worst['pos']) &
                    (players['price'] <= bud) &
                    (~players['id'].isin(my_player_ids))
                ].nlargest(TRANSFER_TARGET_COUNT, 'ict_index').copy()

                targets['next_3_fixtures'] = targets['team'].apply(
                    lambda tid: get_short_fixture_run(tid, fixtures_raw, data, num_gws=3)
                )
                # For defenders/keepers, include CS probability
                is_def_gkp = worst['pos'] in ('DEF', 'GKP')
                targets = add_projection_columns(targets, horizon_gws=3)
                t_cols = [
                    'web_name', 'team_name', 'pos', 'price',
                    'proj_pts', 'play_prob', 'xpts',
                    'form',
                    'expected_goals', 'expected_assists', 'expected_goal_involvements', 'expected_goals_conceded',
                    'ppm', 'ict_index', 'total_points',
                    'avg_minutes', 'selected_by_percent', 'next_3_fixtures',
                ]
                if is_def_gkp:
                    t_cols.insert(-1, 'cs_prob')
                display = get_display_df(targets, t_cols)
                st.dataframe(display, width="stretch", hide_index=True)

                # On-demand explainability: compare one target vs the sell player
                with st.expander("Why this replacement?", expanded=False):
                    _opts = targets["web_name"].tolist()
                    if _opts:
                        _pick = st.selectbox(
                            "Target to explain",
                            options=_opts,
                            index=0,
                            key=f"why_pick_{worst['web_name']}",
                            help="Shows a side-by-side comparison of the sell vs selected buy candidate.",
                        )
                        _buy = targets[targets["web_name"] == _pick].head(1)
                        _sell = worst.to_frame().T.copy()
                        if not _buy.empty:
                            cmp = pd.concat(
                                [
                                    _sell.assign(role="Sell"),
                                    _buy.assign(role="Buy"),
                                ],
                                ignore_index=True,
                            )
                            cmp_cols = [
                                "role",
                                "web_name",
                                "team_name",
                                "pos",
                                "price",
                                "proj_pts",
                                "confidence_tier",
                                "variance_flags",
                                "play_prob",
                                "form",
                                "ict_index",
                                "expected_goals",
                                "expected_assists",
                                "avg_minutes",
                                "rotation_risk",
                                "selected_by_percent",
                                "next_3_fixtures",
                            ]
                            st.dataframe(get_display_df(cmp, cmp_cols), width="stretch", hide_index=True)
                            st.caption(
                                f"Projected gain (horizon): {float(_buy.iloc[0]['proj_pts']) - float(_sell.iloc[0].get('proj_pts', 0)):.1f} points."
                            )
                    else:
                        st.info("No targets available to explain under current constraints.")
                st.download_button(
                    f"Download targets for {worst['web_name']}",
                    df_to_csv(display),
                    file_name=f"targets_{worst['web_name']}.csv",
                    mime="text/csv",
                    key=f"dl_{worst['web_name']}",
                )

        # --- Multi-GW Transfer Planner ---
        st.markdown("---")
        st.header("Multi‑GW Transfer Planner")
        st.caption("Estimates gains over a short horizon using form × fixtures × play probability. This is a heuristic (not an exact model).")

        p1, p2, p3, p4 = st.columns([1, 1, 1, 2])
        with p1:
            plan_horizon = st.selectbox("Horizon (GWs)", [2, 3, 4, 5], index=1, help="How many upcoming GWs to optimize for.", key="plan_horizon")
        with p2:
            free_transfers = st.selectbox(
                "Free transfers",
                [0, 1, 2, 3, 4, 5],
                index=1,
                help="FPL allows you to bank free transfers up to 5.",
                key="plan_fts",
            )
        with p3:
            take_hits = st.toggle("Allow hits", value=False, help="If enabled, planner can suggest more than your free transfers.", key="plan_hits")
        with p4:
            hit_cost = st.number_input("Hit cost (pts)", min_value=0, max_value=12, value=4, step=1, help="Usually 4 points per extra transfer.", key="plan_hit_cost")

        squad_proj = add_projection_columns(my_squad, horizon_gws=int(plan_horizon))
        pool_proj = add_projection_columns(players, horizon_gws=int(plan_horizon))

        # Budget model: keep it simple (assume you can spend +buffer per transfer)
        budget_buffer = st.slider(
            "Budget buffer (£m)",
            0.0,
            2.0,
            float(TRANSFER_BUDGET_BUFFER),
            0.1,
            help="Extra budget you assume is available beyond the outgoing player's price (e.g., in the bank).",
            key="plan_buffer",
        )

        # Choose candidate outs by lowest projected points per £m (value) and minutes risk
        squad_proj["value_proj"] = (squad_proj["proj_pts"] / squad_proj["price"].clip(lower=0.1)).round(2)
        outs = squad_proj.sort_values(["value_proj", "proj_pts"], ascending=[True, True]).head(5).copy()
        st.subheader("Suggested players to consider selling")
        out_cols = ["web_name", "team_name", "pos", "price", "proj_pts", "play_prob", "avg_minutes", "rotation_risk", "value_proj"]
        st.dataframe(get_display_df(outs, out_cols), width="stretch", hide_index=True)

        st.subheader("Best replacements (by projected points)")
        planned_transfers = []
        max_transfers = free_transfers if not take_hits else max(6, free_transfers)

        for _, out in outs.iterrows():
            out_id = int(out["id"])
            bud = float(out["price"]) + float(budget_buffer)
            cand = pool_proj[
                (pool_proj["pos"] == out["pos"])
                & (pool_proj["price"] <= bud)
                & (~pool_proj["id"].isin(my_player_ids))
            ].copy()
            if cand.empty:
                continue
            cand = cand.sort_values("proj_pts", ascending=False).head(10)
            best = cand.iloc[0]
            planned_transfers.append(
                {
                    "Sell": out["web_name"],
                    "Buy": best["web_name"],
                    "Pos": out["pos"],
                    "Sell £m": float(out["price"]),
                    "Buy £m": float(best["price"]),
                    "Sell proj": float(out["proj_pts"]),
                    "Buy proj": float(best["proj_pts"]),
                    "Gain": float(best["proj_pts"] - out["proj_pts"]),
                    "Buy team": best["team_name"],
                    "Buy play_prob": float(best["play_prob"]),
                }
            )

        if planned_transfers:
            plan_df = pd.DataFrame(planned_transfers).sort_values("Gain", ascending=False)
            if len(plan_df) > max_transfers:
                plan_df = plan_df.head(max_transfers)

            transfers_used = int(len(plan_df))
            extra = max(0, transfers_used - int(free_transfers))
            hit_penalty = (extra * int(hit_cost)) if take_hits else 0
            total_gain = float(plan_df["Gain"].sum()) - float(hit_penalty)

            k1, k2, k3 = st.columns(3)
            k1.metric("Transfers suggested", transfers_used)
            k2.metric("Estimated hit cost", hit_penalty, help="Only applies when transfers exceed free transfers and hits are enabled.")
            k3.metric("Net projected gain", round(total_gain, 1), help="Sum of projected gains minus hit cost.")

            st.dataframe(plan_df, width="stretch", hide_index=True)
            st.download_button(
                "Download transfer plan CSV",
                df_to_csv(plan_df),
                file_name="transfer_plan.csv",
                mime="text/csv",
            )
        else:
            st.info("No transfer suggestions found under your current budget/filters.")

        # --- Transfer Impact Simulator (1–3 transfers) ---
        st.markdown("---")
        st.header("Transfer Impact Simulator")
        st.caption("Pick transfers and see the projected impact on your optimized XI (heuristic). Enforces basic constraints (budget, max 3 per team).")

        sim1, sim2, sim3 = st.columns([1, 1, 2])
        with sim1:
            sim_horizon = st.selectbox("Projection horizon (GWs)", [1, 2, 3, 4, 5, 6], index=2, key="sim_horizon")
        with sim2:
            sim_n = st.selectbox("Transfers to simulate", [1, 2, 3], index=0, key="sim_n")
        with sim3:
            sim_buffer = st.slider("Budget buffer (£m)", 0.0, 3.0, 0.5, 0.1, key="sim_buffer", help="Assumed available bank per transfer (approx).")

        sim_squad = add_projection_columns(my_squad.copy(), horizon_gws=int(sim_horizon))
        sim_pool = add_projection_columns(players.copy(), horizon_gws=int(sim_horizon))

        # Team limit check helper
        def _team_limit_ok(ids: list[int]) -> bool:
            try:
                teams_count = players[players["id"].isin(ids)]["team"].value_counts()
                return bool((teams_count <= 3).all())
            except Exception:
                return True

        transfers_chosen: list[dict] = []
        current_ids = [int(x) for x in my_player_ids]
        remaining_ids = current_ids.copy()

        for i in range(int(sim_n)):
            st.subheader(f"Transfer {i+1}")
            s1, s2, s3 = st.columns([1, 1, 1])
            with s1:
                sell_name = st.selectbox(
                    "Sell",
                    options=sim_squad["web_name"].tolist(),
                    index=min(i, max(0, len(sim_squad) - 1)),
                    key=f"sim_sell_{i}",
                )
            sell_row = sim_squad[sim_squad["web_name"] == sell_name].head(1)
            if sell_row.empty:
                continue
            sell_id = int(sell_row.iloc[0]["id"])
            sell_pos = str(sell_row.iloc[0]["pos"])
            sell_price = float(sell_row.iloc[0]["price"])
            max_price = sell_price + float(sim_buffer)

            candidates = sim_pool[
                (sim_pool["pos"] == sell_pos)
                & (sim_pool["price"] <= max_price)
                & (~sim_pool["id"].isin(remaining_ids))
            ].copy()
            candidates = candidates.sort_values(["proj_pts", "play_prob"], ascending=[False, False]).head(100)
            buy_options = candidates["web_name"].tolist()

            with s2:
                buy_name = st.selectbox(
                    "Buy",
                    options=buy_options if buy_options else ["— No candidates —"],
                    index=0,
                    key=f"sim_buy_{i}",
                )
            if not buy_options or buy_name == "— No candidates —":
                st.info("No valid buy candidates under current filters/budget.")
                continue

            buy_row = candidates[candidates["web_name"] == buy_name].head(1)
            if buy_row.empty:
                continue
            buy_id = int(buy_row.iloc[0]["id"])

            # Preview constraint check
            proposed_ids = [pid for pid in remaining_ids if pid != sell_id] + [buy_id]
            with s3:
                ok = _team_limit_ok(proposed_ids)
                st.metric("Team-limit OK", "Yes" if ok else "No", help="FPL limit: max 3 players per real team.")
                if not ok:
                    st.warning("This move breaks the 3-per-team rule.")

            transfers_chosen.append(
                {
                    "Sell": sell_name,
                    "Buy": buy_name,
                    "Sell id": sell_id,
                    "Buy id": buy_id,
                    "Pos": sell_pos,
                    "Budget £m": round(max_price, 1),
                    "Δ proj": round(float(buy_row.iloc[0]["proj_pts"]) - float(sell_row.iloc[0]["proj_pts"]), 1),
                    "Buy play_prob": float(buy_row.iloc[0]["play_prob"]),
                    "Buy variance": str(buy_row.iloc[0].get("variance_flags", "—")),
                }
            )

            # Apply sequentially (so later transfers can't buy already bought players)
            remaining_ids = proposed_ids

        if transfers_chosen:
            st.markdown("---")
            sim_df = pd.DataFrame(transfers_chosen)
            st.dataframe(sim_df, width="stretch", hide_index=True)

            # Before/After optimized XI delta
            before = add_projection_columns(my_squad.copy(), horizon_gws=int(sim_horizon))
            after = add_projection_columns(players[players["id"].isin(remaining_ids)].copy(), horizon_gws=int(sim_horizon))

            try:
                from fpl.logic import optimize_starting_xi as _opt_xi  # type: ignore
                before_xi, _ = _opt_xi(before, score_col="proj_pts", pos_col="pos")
                after_xi, _ = _opt_xi(after, score_col="proj_pts", pos_col="pos")
            except Exception:
                before_xi = before.sort_values("proj_pts", ascending=False).head(11).copy()
                after_xi = after.sort_values("proj_pts", ascending=False).head(11).copy()

            b_pts = float(pd.to_numeric(before_xi["proj_pts"], errors="coerce").fillna(0.0).sum()) if "proj_pts" in before_xi.columns else 0.0
            a_pts = float(pd.to_numeric(after_xi["proj_pts"], errors="coerce").fillna(0.0).sum()) if "proj_pts" in after_xi.columns else 0.0
            d_pts = round(a_pts - b_pts, 1)

            k1, k2, k3 = st.columns(3)
            k1.metric("XI projected (before)", round(b_pts, 1))
            k2.metric("XI projected (after)", round(a_pts, 1))
            k3.metric("Δ XI projected", d_pts)

            st.subheader("Optimized XI — Before")
            st.dataframe(get_display_df(before_xi, xi_cols), width="stretch", hide_index=True)
            st.subheader("Optimized XI — After")
            st.dataframe(get_display_df(after_xi, xi_cols), width="stretch", hide_index=True)
    else:
        st.info("Enter your Manager ID in the sidebar to use the Transfer Optimizer.")

# ── TAB 10: WILDCARD ────────────────────────────────────────────────────────
with tabs[10]:
    st.header("Wildcard Planner")

    # ── Controls row ────────────────────────────────────────────────────────
    wc_ctrl1, wc_ctrl2, wc_ctrl3, wc_ctrl4 = st.columns([2, 1, 1, 1])
    with wc_ctrl1:
        # Default wildcard budget from your current squad value + bank (if available).
        _budget_default = TOTAL_BUDGET
        _bank_default = 0.0
        _squad_value_default = round(float(my_squad["price"].sum()), 1) if not my_squad.empty else None
        if my_id:
            try:
                _entry = get_manager_entry(my_id)
                _bank = float(_entry.get("last_deadline_bank", 0)) / 10.0       # money in the bank in £m
                _bank_default = round(_bank, 1)
                if _squad_value_default is not None:
                    # Match "My Team" (sum of player prices) + bank.
                    _budget_default = round(float(_squad_value_default) + float(_bank_default), 1)
                else:
                    # Fallback: API value includes squad value already.
                    _value = float(_entry.get("last_deadline_value", 1000)) / 10.0
                    _budget_default = round(_value + _bank_default, 1)
            except Exception:
                if _squad_value_default is not None:
                    _budget_default = float(_squad_value_default)
        wc_budget = st.number_input(
            "Total Budget (£m)",
            min_value=80.0,
            max_value=120.0,
            value=float(_budget_default),
            step=0.1,
            help="Defaults to your current squad value + bank when Manager ID is set.",
        )
        if _squad_value_default is not None:
            st.caption(f"Baseline: squad £{_squad_value_default:.1f}m + bank £{_bank_default:.1f}m")
    with wc_ctrl2:
        if not my_squad.empty:
            if st.button("Pre-fill from my squad", use_container_width=True,
                         help="Load your current squad into the builder"):
                # Store by unique player ID to avoid name collisions (e.g. multiple "Henderson").
                st.session_state['wc_gkp_ids'] = my_squad[my_squad['pos'] == 'GKP']['id'].astype(int).tolist()[:2]
                st.session_state['wc_def_ids'] = my_squad[my_squad['pos'] == 'DEF']['id'].astype(int).tolist()[:5]
                st.session_state['wc_mid_ids'] = my_squad[my_squad['pos'] == 'MID']['id'].astype(int).tolist()[:5]
                st.session_state['wc_fwd_ids'] = my_squad[my_squad['pos'] == 'FWD']['id'].astype(int).tolist()[:3]
                st.rerun()
        else:
            st.caption("Enter Manager ID to pre-fill")
    with wc_ctrl3:
        if st.button("Clear squad", use_container_width=True):
            for _k in ['wc_gkp_ids', 'wc_def_ids', 'wc_mid_ids', 'wc_fwd_ids']:
                st.session_state[_k] = []
            st.rerun()

    # ── Position selectors ──────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Pick Your 15")
    st.caption("Select players position by position. The budget bar and squad metrics update live.")

    def _player_label(row: pd.Series) -> str:
        return f"{row['web_name']} ({team_short_map.get(int(row['team']), row['team_name'])} · £{row['price']:.1f})"

    _pos_frames = {p: players[players['pos'] == p].copy() for p in ['GKP', 'DEF', 'MID', 'FWD']}
    _options_by_pos = {}
    _label_to_id_by_pos = {}
    _id_to_label_by_pos = {}
    for _p, _dfp in _pos_frames.items():
        _dfp = _dfp.sort_values(["team_name", "web_name"])
        _labels = _dfp.apply(_player_label, axis=1).tolist()
        _ids = _dfp["id"].astype(int).tolist()
        _options_by_pos[_p] = _labels
        _label_to_id_by_pos[_p] = dict(zip(_labels, _ids))
        _id_to_label_by_pos[_p] = dict(zip(_ids, _labels))

    # Optional team filter to avoid scrolling huge lists.
    wc_team_filter = st.selectbox(
        "Team filter (optional)",
        ["All teams"] + sorted(list(team_map.values())),
        index=0,
        help="Filter the player picklists by team to reduce scrolling.",
        key="wc_team_filter",
    )

    def _filter_labels_by_team(pos_key: str) -> list[str]:
        if wc_team_filter == "All teams":
            return _options_by_pos[pos_key]
        dfp = _pos_frames[pos_key]
        dfp = dfp[dfp["team_name"] == wc_team_filter]
        dfp = dfp.sort_values(["web_name"])
        return dfp.apply(_player_label, axis=1).tolist()

    sel_col1, sel_col2 = st.columns(2)
    with sel_col1:
        _pref_gkp_labels = [
            _id_to_label_by_pos["GKP"].get(int(pid))
            for pid in st.session_state.get("wc_gkp_ids", [])
        ]
        _pref_gkp_labels = [x for x in _pref_gkp_labels if x]
        selected_gkp_labels = st.multiselect(
            "Goalkeepers — pick 2",
            options=_filter_labels_by_team("GKP"),
            default=_pref_gkp_labels,
            max_selections=2,
            key='wc_gkp_labels',
            help="Pick by name + team + price to avoid duplicates.",
        )
        _pref_def_labels = [
            _id_to_label_by_pos["DEF"].get(int(pid))
            for pid in st.session_state.get("wc_def_ids", [])
        ]
        _pref_def_labels = [x for x in _pref_def_labels if x]
        selected_def_labels = st.multiselect(
            "Defenders — pick 5",
            options=_filter_labels_by_team("DEF"),
            default=_pref_def_labels,
            max_selections=5,
            key='wc_def_labels',
        )
    with sel_col2:
        _pref_mid_labels = [
            _id_to_label_by_pos["MID"].get(int(pid))
            for pid in st.session_state.get("wc_mid_ids", [])
        ]
        _pref_mid_labels = [x for x in _pref_mid_labels if x]
        selected_mid_labels = st.multiselect(
            "Midfielders — pick 5",
            options=_filter_labels_by_team("MID"),
            default=_pref_mid_labels,
            max_selections=5,
            key='wc_mid_labels',
        )
        _pref_fwd_labels = [
            _id_to_label_by_pos["FWD"].get(int(pid))
            for pid in st.session_state.get("wc_fwd_ids", [])
        ]
        _pref_fwd_labels = [x for x in _pref_fwd_labels if x]
        selected_fwd_labels = st.multiselect(
            "Forwards — pick 3",
            options=_filter_labels_by_team("FWD"),
            default=_pref_fwd_labels,
            max_selections=3,
            key='wc_fwd_labels',
        )

    # ── Budget & completion status ──────────────────────────────────────────
    # Convert selected labels → ids (unique) and merge with prefill ids (if present).
    _sel_ids = []
    for _p, _labels in [
        ("GKP", selected_gkp_labels),
        ("DEF", selected_def_labels),
        ("MID", selected_mid_labels),
        ("FWD", selected_fwd_labels),
    ]:
        _m = _label_to_id_by_pos[_p]
        _sel_ids.extend([int(_m[l]) for l in _labels if l in _m])

    # Apply prefill ids (if present) when user hasn't selected anything yet.
    if not _sel_ids:
        _prefill = (
            st.session_state.get("wc_gkp_ids", [])
            + st.session_state.get("wc_def_ids", [])
            + st.session_state.get("wc_mid_ids", [])
            + st.session_state.get("wc_fwd_ids", [])
        )
        _sel_ids = [int(x) for x in _prefill]

    wc_squad_df = players[players['id'].isin(_sel_ids)].copy()
    _wc_cost = round(wc_squad_df['price'].sum(), 1) if not wc_squad_df.empty else 0.0
    _wc_remaining = round(wc_budget - _wc_cost, 1)
    _wc_slots_filled = int(len(wc_squad_df))
    _wc_gws_left = (38 - curr_gw_id) if curr_gw_id else 0

    _wc_pos_counts = wc_squad_df["pos"].value_counts().to_dict() if not wc_squad_df.empty else {}
    _wc_gkp_n = int(_wc_pos_counts.get("GKP", 0))
    _wc_def_n = int(_wc_pos_counts.get("DEF", 0))
    _wc_mid_n = int(_wc_pos_counts.get("MID", 0))
    _wc_fwd_n = int(_wc_pos_counts.get("FWD", 0))

    st.markdown("---")
    # Budget progress bar
    _bar_pct = min(_wc_cost / wc_budget, 1.0)
    _bar_label = f"Budget used: £{_wc_cost:.1f}m of £{wc_budget:.1f}m"
    st.progress(_bar_pct, text=_bar_label)

    # Status metrics
    stat1, stat2, stat3, stat4, stat5 = st.columns(5)
    stat1.metric("Remaining Budget", f"£{_wc_remaining}m",
                 delta=f"{'over' if _wc_remaining < 0 else 'free'}")
    stat2.metric("Players Selected", f"{_wc_slots_filled} / 15")
    stat3.metric("GWs Remaining", _wc_gws_left)
    if not wc_squad_df.empty:
        stat4.metric("Squad xPts", round(wc_squad_df['xpts'].sum(), 1))
        stat5.metric("Avg PPM", round(wc_squad_df['ppm'].mean(), 1))

    # Position completion chips
    pos_st1, pos_st2, pos_st3, pos_st4 = st.columns(4)
    for _col, _pos, _n, _target in [
        (pos_st1, "GKP", _wc_gkp_n, 2), (pos_st2, "DEF", _wc_def_n, 5),
        (pos_st3, "MID", _wc_mid_n, 5), (pos_st4, "FWD", _wc_fwd_n, 3),
    ]:
        _label = f"{_pos}  {_n}/{_target}"
        _delta = "complete" if _n == _target else f"{_target - _n} more needed"
        _col.metric(_label, "", delta=_delta, delta_color="normal" if _n == _target else "inverse")

    if _wc_remaining < 0:
        st.error(f"Over budget by £{abs(_wc_remaining):.1f}m — swap out a player to fix this.")
    elif _wc_slots_filled == 15:
        st.success(f"Squad complete! £{_wc_remaining:.1f}m in the bank.")

    # ── Squad summary ───────────────────────────────────────────────────────
    if not wc_squad_df.empty:
        st.markdown("---")
        st.subheader("Squad Summary")

        # Per-position cost breakdown
        _pos_cost = wc_squad_df.groupby('pos')['price'].agg(['sum', 'mean', 'count']).reset_index()
        _pos_cost.columns = ['Pos', 'Total £m', 'Avg £m', 'Players']
        _pos_cost['Total £m'] = _pos_cost['Total £m'].round(1)
        _pos_cost['Avg £m'] = _pos_cost['Avg £m'].round(1)
        pc1, pc2 = st.columns([1, 2])
        with pc1:
            st.markdown("**Budget by position**")
            st.dataframe(_pos_cost, width="stretch", hide_index=True)
        with pc2:
            _pos_order = ['GKP', 'DEF', 'MID', 'FWD']
            _cost_ordered = _pos_cost.set_index('Pos').reindex(_pos_order).dropna()
            fig_wc_budget = go.Figure(go.Bar(
                x=_cost_ordered.index, y=_cost_ordered['Total £m'],
                marker_color=['#38003c', '#00753e', '#01fc7a', '#ff1751'],
                text=_cost_ordered['Total £m'].apply(lambda v: f"£{v}m"),
                textposition='outside',
            ))
            fig_wc_budget.update_layout(
                yaxis_title="£m", margin=dict(l=20, r=20, t=20, b=20),
                showlegend=False,
            )
            st.plotly_chart(fig_wc_budget, width="stretch")

        # Squad rows by position
        _sq_display_cols = [
            'web_name', 'team_name', 'pos', 'price',
            'proj_pts', 'play_prob', 'xpts',
            'form',
            'expected_goals', 'expected_assists', 'expected_goal_involvements', 'expected_goals_conceded',
            'ppm', 'ict_index', 'total_points',
            'avg_minutes', 'next_3_fixtures',
        ]
        for _pos_label in ['GKP', 'DEF', 'MID', 'FWD']:
            _pos_df = wc_squad_df[wc_squad_df['pos'] == _pos_label].copy()
            if _pos_df.empty:
                continue
            _pos_df['next_3_fixtures'] = _pos_df['team'].apply(
                lambda tid: get_short_fixture_run(tid, fixtures_raw, data, num_gws=3)
            )
            _cols = _sq_display_cols[:]
            if _pos_label in ('GKP', 'DEF'):
                _cols.insert(-1, 'cs_prob')
            _pos_total = _pos_df['price'].sum()
            st.markdown(f"**{_pos_label}** — {len(_pos_df)} players · £{_pos_total:.1f}m")
            st.dataframe(get_display_df(_pos_df, _cols), width="stretch", hide_index=True)

        st.download_button(
            "Download Squad CSV",
            df_to_csv(get_display_df(
                wc_squad_df,
                [
                    'web_name', 'team_name', 'pos', 'price',
                    'proj_pts', 'play_prob', 'xpts',
                    'form',
                    'expected_goals', 'expected_assists', 'expected_goal_involvements', 'expected_goals_conceded',
                    'ppm', 'ict_index', 'total_points',
                ],
            )),
            file_name="wildcard_squad.csv", mime="text/csv",
        )

    # ── Player Browser ──────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Player Browser")
    st.caption("Research players by position before adding them in the selectors above.")

    pb1, pb2, pb3, pb4 = st.columns(4)
    with pb1:
        browser_pos = st.radio("Position", ['GKP', 'DEF', 'MID', 'FWD'], horizontal=True, key="wc_pb_pos")
    with pb2:
        _pos_max = float(players[players['pos'] == browser_pos]['price'].max())
        # Reset the slider when changing position so it doesn't get stuck at an old (e.g. 6.0) value.
        if st.session_state.get("wc_pb_pos_prev") != browser_pos:
            st.session_state["wc_pb_pos_prev"] = browser_pos
            st.session_state["wc_pb_price"] = float(_pos_max)
        browser_max_price = st.slider(
            "Max Price (£m)",
            3.5,
            _pos_max,
            _pos_max,
            step=0.5,
            key="wc_pb_price",
            help="Controls which players appear below. Set to the max to see premium options.",
        )
    with pb3:
        browser_sort = st.selectbox(
            "Sort by", ['xPts', 'PPM', 'Form', 'ICT', 'Total Pts', 'Ownership %'],
            key="wc_pb_sort",
        )
    with pb4:
        hide_picked = st.checkbox("Hide already selected", value=True, key="wc_pb_hide")

    pb5, pb6 = st.columns([1, 2])
    with pb5:
        browser_team = st.selectbox(
            "Team",
            ["All teams"] + sorted(list(team_map.values())),
            index=0,
            key="wc_pb_team",
            help="Filter by team to avoid scrolling long lists.",
        )
    with pb6:
        browser_search = st.text_input(
            "Search name",
            value="",
            key="wc_pb_search",
            help="Type part of a player's name (case-insensitive).",
        )

    _pb_sort_map = {
        'xPts': 'xpts', 'PPM': 'ppm', 'Form': 'form',
        'ICT': 'ict_index', 'Total Pts': 'total_points', 'Ownership %': 'selected_by_percent',
    }
    browser_df = players[
        (players['pos'] == browser_pos) &
        (players['price'] <= browser_max_price)
    ].copy()
    if browser_team != "All teams":
        browser_df = browser_df[browser_df["team_name"] == browser_team]
    if browser_search.strip():
        browser_df = browser_df[browser_df["web_name"].str.contains(browser_search.strip(), case=False, na=False)]
    if hide_picked:
        browser_df = browser_df[~browser_df['id'].isin(_sel_ids)]

    browser_df['next_3_fixtures'] = browser_df['team'].apply(
        lambda tid: get_short_fixture_run(tid, fixtures_raw, data, num_gws=3)
    )
    browser_df = add_projection_columns(browser_df, horizon_gws=3)
    _pb_cols = [
        'web_name', 'team_name', 'pos', 'price',
        'proj_pts', 'play_prob', 'xpts',
        'form',
        'expected_goals', 'expected_assists', 'expected_goal_involvements', 'expected_goals_conceded',
        'ppm', 'ict_index', 'total_points',
        'avg_minutes', 'selected_by_percent', 'next_3_fixtures',
    ]
    if browser_pos in ('GKP', 'DEF'):
        _pb_cols.insert(-1, 'cs_prob')

    st.dataframe(
        get_display_df(
            browser_df.sort_values(_pb_sort_map[browser_sort], ascending=False).head(30),
            _pb_cols,
        ),
        use_container_width=True, hide_index=True,
    )
