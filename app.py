import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as go

# ==========================================
# 1. PAGE CONFIGURATION & CSS
# ==========================================
st.set_page_config(page_title="FPL Elite Dashboard", layout="wide")

st.markdown("""
    <style>
    [data-testid="stMetricLabel"] div, [data-testid="stMetricLabel"] p {
        color: #111827 !important; font-weight: 700 !important;
    }
    .stMarkdown h3 { color: #111827 !important; }
    [data-testid="stMetricValue"] div { color: #000000 !important; }
    [data-testid="stMetric"] {
        background-color: #ffffff !important; border: 1px solid #e2e8f0 !important;
        border-radius: 10px !important; padding: 10px !important;
    }
    section[data-testid="stSidebar"] .stMarkdown p,
    section[data-testid="stSidebar"] .stMarkdown h3 { color: #ffffff !important; }
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 2. CONSTANTS
# ==========================================
FPL_BASE_URL = "https://fantasy.premierleague.com/api/"
REQUEST_TIMEOUT = 10

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
    "total_points": "Pts", "form": "Form", "ict_index": "ICT",
    "expected_goals": "xG", "efficiency": "Eff Score",
    "selected_by_percent": "Own%", "cost_change_event": "Price Change",
    "chance_of_playing_next_round": "Avail%", "news": "News",
    "next_3_fixtures": "Next 3 Fix", "xpts": "xPts",
    "live_pts": "Live Pts", "live_bonus": "Bonus",
    "live_minutes": "Mins", "diff_score": "Diff Score",
    "ppm": "PPM", "net_transfers": "Net Transf",
    "avg_minutes": "Avg Mins", "form_trend": "Form Trend",
    "cs_prob": "CS%", "rotation_risk": "Rot. Risk",
    "season_ppg": "PPG",
}

# ==========================================
# 3. DATA FETCHING
# ==========================================
@st.cache_data(ttl=3600)
def get_fpl_data():
    bootstrap_resp = requests.get(f"{FPL_BASE_URL}bootstrap-static/", timeout=REQUEST_TIMEOUT)
    bootstrap_resp.raise_for_status()
    fixtures_resp = requests.get(f"{FPL_BASE_URL}fixtures/", timeout=REQUEST_TIMEOUT)
    fixtures_resp.raise_for_status()
    return bootstrap_resp.json(), fixtures_resp.json()

@st.cache_data(ttl=3600)
def get_manager_history(manager_id):
    resp = requests.get(f"{FPL_BASE_URL}entry/{manager_id}/history/", timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()

@st.cache_data(ttl=300)
def get_manager_entry(manager_id):
    resp = requests.get(f"{FPL_BASE_URL}entry/{manager_id}/", timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()

@st.cache_data(ttl=300)
def get_transfer_history(manager_id):
    resp = requests.get(f"{FPL_BASE_URL}entry/{manager_id}/transfers/", timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()

@st.cache_data(ttl=300)
def get_league_standings(league_id):
    resp = requests.get(f"{FPL_BASE_URL}leagues-classic/{league_id}/standings/", timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()

@st.cache_data(ttl=300)
def get_h2h_standings(league_id):
    resp = requests.get(f"{FPL_BASE_URL}leagues-h2h/{league_id}/standings/", timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()

@st.cache_data(ttl=3600)
def get_player_history(player_id):
    resp = requests.get(f"{FPL_BASE_URL}element-summary/{player_id}/", timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()

@st.cache_data(ttl=60)
def get_live_gw_data(gw_id):
    """Live player stats for an active gameweek. Short 60s TTL."""
    resp = requests.get(f"{FPL_BASE_URL}event/{gw_id}/live/", timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()

try:
    data, fixtures_raw = get_fpl_data()
except requests.RequestException as e:
    st.error(f"Failed to load FPL data: {e}")
    st.stop()

players = pd.DataFrame(data['elements'])
teams = pd.DataFrame(data['teams'])
team_map = dict(zip(teams['id'], teams['name']))
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
    'expected_goals', 'expected_assists', 'ict_index', 'form',
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

def fetch_squad_picks(manager_id, gw_id):
    url = f"{FPL_BASE_URL}entry/{manager_id}/event/{gw_id}/picks/"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get('picks', [])
    except requests.RequestException:
        return None

def df_to_csv(df):
    return df.to_csv(index=False).encode('utf-8')

def get_chip_status(used_chips):
    """Return dict of chip_name -> GW used (or None if available)."""
    # Each chip can only be used once, except wildcard (twice: one per half)
    wildcard_uses = [c for c in used_chips if c['name'] == 'wildcard']
    status = {}
    for chip_key, chip_label in ALL_CHIPS.items():
        uses = [c for c in used_chips if c['name'] == chip_key]
        if chip_key == 'wildcard':
            # Two wildcards per season
            gws = [str(c['event']) for c in uses]
            if len(uses) >= 2:
                status[chip_label] = f"Used (GW{', GW'.join(gws)})"
            elif len(uses) == 1:
                status[chip_label] = f"1 used (GW{gws[0]}) — 1 remaining"
            else:
                status[chip_label] = "Available (x2)"
        else:
            if uses:
                status[chip_label] = f"Used (GW{uses[0]['event']})"
            else:
                status[chip_label] = "Available"
    return status

# ==========================================
# 7. SIDEBAR & SQUAD LOGIC
# ==========================================
st.sidebar.header("Manager Settings")
my_id = st.sidebar.text_input("Manager ID", value=st.query_params.get("id", ""))
if my_id:
    st.query_params["id"] = my_id

fixture_lookahead = st.sidebar.slider("Fixture Lookahead (GWs)", min_value=3, max_value=8, value=5)

with st.sidebar.expander("Advanced Thresholds"):
    FORM_TC_THRESHOLD = st.slider("TC Form Min", 3.0, 9.0, FORM_TC_THRESHOLD, step=0.5,
                                  help="Minimum form score to suggest Triple Captain")
    BLANK_FREE_HIT_THRESHOLD = st.slider("FH Blank Threshold", 2, 6, BLANK_FREE_HIT_THRESHOLD,
                                         help="Blanked players needed to suggest Free Hit")
    DGW_BENCH_BOOST_THRESHOLD = st.slider("BB DGW Players", 2, 5, DGW_BENCH_BOOST_THRESHOLD,
                                           help="DGW players on bench to suggest Bench Boost")
    DIFF_MAX_OWNERSHIP = st.slider("Differential Cutoff %", 1.0, 20.0, float(DIFF_MAX_OWNERSHIP), step=1.0,
                                   help="Ownership threshold for differential status")

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

        squad_cols = ['web_name', 'team_name', 'pos', 'price', 'form', 'form_trend', 'xpts', 'ppm', 'total_points', 'ict_index', 'avg_minutes', 'rotation_risk', 'selected_by_percent']
        starters = my_squad[my_squad['multiplier'] > 0].sort_values('position')
        bench = my_squad[my_squad['multiplier'] == 0].sort_values('position')

        st.subheader("Starting XI")
        st.dataframe(get_display_df(starters, squad_cols), use_container_width=True, hide_index=True)

        # --- Bench Analysis ---
        st.subheader("Bench")
        st.dataframe(get_display_df(bench, squad_cols), use_container_width=True, hide_index=True)

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
        st.plotly_chart(fig_form_avg, use_container_width=True)

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

                c_cols = st.columns(3)
                for i, (_, row) in enumerate(cap_df.nlargest(3, 'Score').iterrows()):
                    with c_cols[i]:
                        st.subheader(f"#{i+1}: {row['web_name']}")
                        st.write(f"vs **{row['Opp']}** ({row['Loc']})")
                        d = row['Diff']
                        color = "green" if d <= 2 else "orange" if d <= 3 else "red"
                        st.markdown(f"Difficulty: :{color}[Level {d}]")
                        st.metric("Cap Score", row['Score'])
                        st.caption(f"Tier: {row['Tier']}  |  ICT norm: {row['ict_norm']}")
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
                is_used = status.startswith("Used (GW") or status.startswith("1 used")
                col.metric(chip_label, status if is_used else "Available")
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

                live_cols = ['web_name', 'team_name', 'pos', 'live_minutes', 'live_pts', 'live_bonus', 'live_goals', 'live_assists', 'multiplier']
                live_rename = {
                    'web_name': 'Player', 'team_name': 'Team', 'pos': 'Pos',
                    'live_minutes': 'Mins', 'live_pts': 'Pts', 'live_bonus': 'Bonus',
                    'live_goals': 'Goals', 'live_assists': 'Assists', 'multiplier': 'Mult',
                }
                live_starters = live_squad[live_squad['multiplier'] > 0].sort_values('position')
                live_bench = live_squad[live_squad['multiplier'] == 0].sort_values('position')

                st.subheader("Starting XI — Live")
                display_live = live_starters[[c for c in live_cols if c in live_starters.columns]]
                st.dataframe(display_live.rename(columns=live_rename), use_container_width=True, hide_index=True)

                st.subheader("Bench — Live")
                display_bench = live_bench[[c for c in live_cols if c in live_bench.columns]]
                st.dataframe(display_bench.rename(columns=live_rename), use_container_width=True, hide_index=True)
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
                live_df = live_df.merge(players[['id', 'web_name', 'team_name', 'pos', 'price', 'selected_by_percent']], on='id', how='left')
                top_live_cols = ['web_name', 'team_name', 'pos', 'price', 'live_pts', 'live_bonus', 'live_minutes', 'selected_by_percent']
                top_live_rename = {
                    'web_name': 'Player', 'team_name': 'Team', 'pos': 'Pos', 'price': '£m',
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
                st.plotly_chart(fig, use_container_width=True)

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
                st.plotly_chart(fig2, use_container_width=True)

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
                    st.plotly_chart(fig_pos, use_container_width=True)
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
                st.dataframe(hist_df[available].rename(columns=rename), use_container_width=True, hide_index=True)
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
                    st.plotly_chart(fig_hits, use_container_width=True)

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
        min_p = st.slider("Min Price (£m)", 3.5, 14.5, 3.5, step=0.5, key="scout_min_p")
    with s2:
        max_p = st.slider("Max Price (£m)", 4.0, 15.0, 15.0, step=0.5, key="scout_p")
    with s3:
        po_filt = st.multiselect("Positions", options=list(pos_map.values()), default=list(pos_map.values()), key="scout_pos")
    with s4:
        t_filt = st.multiselect("Teams", options=sorted(list(team_map.values())), default=sorted(list(team_map.values())), key="scout_team")

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
    scout_cols = ['web_name', 'team_name', 'pos', 'price', 'xpts', 'ppm', 'total_points', 'form', 'form_trend', 'ict_index', 'selected_by_percent']
    if _net_avail:
        scout_cols.insert(-1, 'net_transfers')
    sorted_scout = scout_df.sort_values(_sort_opts[scout_sort], ascending=False)
    st.dataframe(get_display_df(sorted_scout, scout_cols), use_container_width=True, hide_index=True)
    st.download_button(
        "Download Scout CSV",
        df_to_csv(get_display_df(sorted_scout, scout_cols)),
        file_name="player_scout.csv", mime="text/csv",
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
    st.plotly_chart(fig_scatter, use_container_width=True)

    # --- Differential Finder ---
    st.markdown("---")
    st.subheader("Differential Finder")
    st.caption(f"High ICT players owned by fewer than {DIFF_MAX_OWNERSHIP}% of managers. Sorted by differential score (ICT / ownership).")
    diff_max_own = st.slider("Max Ownership %", 2.0, 20.0, float(DIFF_MAX_OWNERSHIP), step=1.0, key="diff_own")
    diffs = players[players['selected_by_percent'] <= diff_max_own].copy()
    diffs['diff_score'] = (diffs['ict_index'] / diffs['selected_by_percent'].clip(lower=0.1)).round(1)
    diff_cols = ['web_name', 'team_name', 'pos', 'price', 'selected_by_percent', 'form', 'ict_index', 'xpts', 'diff_score']
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
        st.dataframe(get_display_df(hot_df, hc_cols), use_container_width=True, hide_index=True)
    with hc2:
        st.markdown("**Coldest Players (form below season avg)**")
        cold_df = scout_df[scout_df['form_trend'] < 0].nsmallest(10, 'form_trend')
        st.dataframe(get_display_df(cold_df, hc_cols), use_container_width=True, hide_index=True)

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
        st.dataframe(get_display_df(rising, rising_cols), use_container_width=True, hide_index=True)
    with pc2:
        st.subheader("Falling — This GW")
        falling = players[players['cost_change_event'] < 0].sort_values('cost_change_event')
        st.dataframe(get_display_df(falling, rising_cols), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Biggest Movers Since Season Start")
    movers = players.copy()
    movers['abs_change'] = movers['cost_change_start'].abs()
    movers = movers.sort_values('abs_change', ascending=False).head(20)
    mover_cols = ['web_name', 'team_name', 'pos', 'price', 'cost_change_start', 'form', 'selected_by_percent']
    st.dataframe(get_display_df(movers, mover_cols), use_container_width=True, hide_index=True)

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
    st.dataframe(get_display_df(rise_candidates, rise_cols), use_container_width=True, hide_index=True)

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
        st.dataframe(_warn_df, use_container_width=True, hide_index=True)
        _next_dgw = next((_r for _r in _warning_rows if _r['# DGW'] > 0), None)
        _next_blank = next((_r for _r in _warning_rows if _r['# Blank'] > 0), None)
        if _next_dgw:
            st.info(f"Next DGW: GW{_next_dgw['GW']} — {_next_dgw['DGW Teams']}")
        if _next_blank:
            st.warning(f"Next Blank GW: GW{_next_blank['GW']} — {_next_blank['Blank Teams']}")
    st.markdown("---")

    sort_by_difficulty = st.toggle("Sort by Easiest Run", value=False)

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
    st.dataframe(styled, use_container_width=True, hide_index=True)
    if my_team_names:
        st.caption("Bold green border = team in your squad.")
    if sort_by_difficulty:
        st.caption("Run Score = sum of difficulty ratings (lower = easier). Blanks=3, DGWs=1.5.")

# ── TAB 6: PLAYER VS ────────────────────────────────────────────────────────
with tabs[6]:
    st.header("Player VS Radar")
    search_mode = st.toggle("Search by player name", value=False)

    if search_mode:
        all_names = sorted(players['web_name'].unique())
        v1, v2 = st.columns(2)
        with v1:
            p1 = st.selectbox("Player 1", all_names, key="vs_p1_search")
            tm1 = players[players['web_name'] == p1]['team_name'].iloc[0] if p1 else None
        with v2:
            p2 = st.selectbox("Player 2", all_names, key="vs_p2_search", index=1)
            tm2 = players[players['web_name'] == p2]['team_name'].iloc[0] if p2 else None
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
        st.plotly_chart(fig_v, use_container_width=True)

        st.subheader("Stats Comparison")
        compare_cols = ['web_name', 'team_name', 'pos', 'price', 'form', 'xpts', 'total_points', 'ict_index', 'expected_goals', 'selected_by_percent']
        p1_row = players[(players['web_name'] == p1) & (players['team_name'] == tm1)]
        p2_row = players[(players['web_name'] == p2) & (players['team_name'] == tm2)]
        st.dataframe(get_display_df(pd.concat([p1_row, p2_row]), compare_cols), use_container_width=True, hide_index=True)

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
        st.plotly_chart(gw_fig, use_container_width=True)

# ── TAB 7: MINI-LEAGUE ──────────────────────────────────────────────────────
with tabs[7]:
    st.header("Mini-League Standings")
    league_type = st.radio("League Type", ["Classic", "Head-to-Head"], horizontal=True)
    league_id = st.text_input("Enter League ID", value=st.query_params.get("league", ""), key="league_input")
    if league_id:
        st.query_params["league"] = league_id

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
                    st.dataframe(league_display, use_container_width=True, hide_index=True)
                    st.download_button("Download Standings CSV", df_to_csv(league_display),
                                       file_name=f"{league_name}_standings.csv", mime="text/csv")

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
                            st.dataframe(form_df, use_container_width=True)
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
                    st.dataframe(h2h_display, use_container_width=True, hide_index=True)
                    st.download_button("Download H2H Standings CSV", df_to_csv(h2h_display),
                                       file_name=f"{league_name}_h2h.csv", mime="text/csv")
                else:
                    st.info("No standings data found.")
        except requests.RequestException:
            st.error("League not found or is private. Check the League ID.")

# ── TAB 8: RIVALS ───────────────────────────────────────────────────────────
with tabs[8]:
    st.header("Rival Deep-Dive")
    rival_id = st.text_input("Enter Rival Manager ID", value=st.query_params.get("rival", ""), key="riv_input")
    if rival_id:
        st.query_params["rival"] = rival_id

    if my_id and rival_id and curr_gw_event:
        picks = fetch_squad_picks(rival_id, curr_gw_id)
        if picks is None:
            st.error("Rival ID not found or request failed.")
        else:
            riv_ids = [p['element'] for p in picks]
            my_set, riv_set = set(my_player_ids), set(riv_ids)
            riv_cols = ['web_name', 'team_name', 'price', 'total_points', 'form', 'ict_index', 'expected_goals', 'selected_by_percent']

            st.subheader("Shield (Shared Assets)")
            st.dataframe(get_display_df(players[players['id'].isin(my_set & riv_set)], riv_cols), use_container_width=True, hide_index=True)
            st.subheader("Your Sword (Differentials)")
            st.dataframe(get_display_df(players[players['id'].isin(my_set - riv_set)], riv_cols), use_container_width=True, hide_index=True)
            st.subheader("Danger (Rival Differentials)")
            st.dataframe(get_display_df(players[players['id'].isin(riv_set - my_set)], riv_cols), use_container_width=True, hide_index=True)

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
                st.plotly_chart(fig_rank, use_container_width=True)
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
        num_ft = st.radio("Free Transfers Available", options=[1, 2, "Wildcard"], horizontal=True)
        n_transfers = 2 if num_ft == "Wildcard" else int(num_ft)

        # Rotation risk in squad: flag players averaging < 55 min
        _rot_risk_players = my_squad[my_squad['rotation_risk'] == 'Low mins']['web_name'].tolist()
        if _rot_risk_players:
            st.warning(f"Rotation risk (low avg mins): {', '.join(_rot_risk_players)}")

        candidates = my_squad.sort_values('efficiency').head(n_transfers)
        st.subheader("Drop Candidates")
        drop_cols = ['web_name', 'team_name', 'pos', 'price', 'form', 'xpts', 'ppm', 'efficiency', 'avg_minutes', 'rotation_risk', 'selected_by_percent']
        st.dataframe(get_display_df(candidates, drop_cols), use_container_width=True, hide_index=True)

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
                t_cols = ['web_name', 'team_name', 'price', 'form', 'xpts', 'ppm', 'ict_index', 'expected_goals', 'total_points', 'avg_minutes', 'selected_by_percent', 'next_3_fixtures']
                if is_def_gkp:
                    t_cols.insert(-1, 'cs_prob')
                display = get_display_df(targets, t_cols)
                st.dataframe(display, use_container_width=True, hide_index=True)
                st.download_button(
                    f"Download targets for {worst['web_name']}",
                    df_to_csv(display),
                    file_name=f"targets_{worst['web_name']}.csv",
                    mime="text/csv",
                    key=f"dl_{worst['web_name']}",
                )
    else:
        st.info("Enter your Manager ID in the sidebar to use the Transfer Optimizer.")

# ── TAB 10: WILDCARD ────────────────────────────────────────────────────────
with tabs[10]:
    st.header("Wildcard Planner")
    st.caption("Build an optimal squad within budget. Pin players you want to keep, then find the best options for remaining slots.")

    wc_budget = st.number_input("Total Budget (£m)", min_value=90.0, max_value=105.0, value=TOTAL_BUDGET, step=0.5)
    all_player_names = sorted(players['web_name'].unique())
    pinned_names = st.multiselect(
        "Pin players to keep",
        options=all_player_names,
        default=[],
        help="These players will be locked in. Budget and slots are calculated around them.",
    )

    pinned_df = players[players['web_name'].isin(pinned_names)].drop_duplicates('web_name')
    pinned_cost = pinned_df['price'].sum()
    remaining_budget = round(wc_budget - pinned_cost, 1)
    pinned_counts = pinned_df['pos'].value_counts().to_dict()
    slots_remaining = {pos: total - pinned_counts.get(pos, 0) for pos, total in SQUAD_COMPOSITION.items()}

    b1, b2, b3 = st.columns(3)
    b1.metric("Remaining Budget", f"£{remaining_budget}m")
    b2.metric("Pinned Players", len(pinned_df))
    b3.metric("Slots to Fill", sum(max(s, 0) for s in slots_remaining.values()))

    if pinned_names:
        st.subheader("Pinned Players")
        st.dataframe(
            get_display_df(pinned_df, ['web_name', 'team_name', 'pos', 'price', 'form', 'xpts', 'ict_index', 'total_points']),
            use_container_width=True, hide_index=True,
        )

    st.subheader("Best Available for Remaining Slots")
    if remaining_budget < 0:
        st.error("Pinned players exceed your budget. Remove some to continue.")
    else:
        total_open_slots = sum(max(s, 0) for s in slots_remaining.values())
        for pos, slots in slots_remaining.items():
            if slots <= 0:
                continue
            with st.expander(f"{pos} — {slots} slot(s) remaining"):
                slot_budget = round(remaining_budget / max(total_open_slots, 1) * slots, 1)
                candidates_wc = players[
                    (players['pos'] == pos) &
                    (~players['web_name'].isin(pinned_names))
                ].nlargest(10, 'ict_index').copy()
                candidates_wc['next_3_fixtures'] = candidates_wc['team'].apply(
                    lambda tid: get_short_fixture_run(tid, fixtures_raw, data, num_gws=3)
                )
                wc_cols = ['web_name', 'team_name', 'price', 'form', 'xpts', 'ppm', 'ict_index', 'total_points', 'avg_minutes', 'selected_by_percent', 'next_3_fixtures']
                if pos in ('DEF', 'GKP'):
                    wc_cols.insert(-1, 'cs_prob')
                st.dataframe(get_display_df(candidates_wc, wc_cols), use_container_width=True, hide_index=True)
                st.caption(f"Suggested budget allocation for {slots} {pos} slot(s): £{slot_budget}m")
