import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as go

# ==========================================
# 1. PAGE CONFIGURATION & SURGICAL CSS
# ==========================================
st.set_page_config(page_title="FPL Elite Dashboard", layout="wide")

st.markdown("""
    <style>
    [data-testid="stMetricLabel"] div, [data-testid="stMetricLabel"] p {
        color: #111827 !important;
        font-weight: 700 !important;
    }
    .stMarkdown h3 {
        color: #111827 !important;
    }
    [data-testid="stMetricValue"] div {
        color: #000000 !important;
    }
    [data-testid="stMetric"] {
        background-color: #ffffff !important;
        border: 1px solid #e2e8f0 !important;
        border-radius: 10px !important;
        padding: 10px !important;
    }
    section[data-testid="stSidebar"] .stMarkdown p,
    section[data-testid="stSidebar"] .stMarkdown h3 {
        color: #ffffff !important;
    }
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 2. CONSTANTS
# ==========================================
FPL_BASE_URL = "https://fantasy.premierleague.com/api/"
REQUEST_TIMEOUT = 10  # seconds

DIFF_COLORS = {
    1: '#00753e',
    2: '#01fc7a',
    3: '#e7e7e7',
    4: '#ff1751',
    5: '#80072d',
}
DIFF_LIGHT_TEXT = {3}

FORM_TC_THRESHOLD = 5.0
BLANK_FREE_HIT_THRESHOLD = 4
DGW_BENCH_BOOST_THRESHOLD = 3
SQUAD_OUTFIELD_SIZE = 11
TRANSFER_BUDGET_BUFFER = 0.5
TRANSFER_TARGET_COUNT = 8
RADAR_METRICS = ['form', 'expected_goals', 'ict_index', 'total_points']

COLUMN_LABELS = {
    "web_name": "Player",
    "team_name": "Team",
    "pos": "Pos",
    "price": "£m",
    "total_points": "Pts",
    "form": "Form",
    "ict_index": "ICT",
    "expected_goals": "xG",
    "efficiency": "Eff Score",
    "selected_by_percent": "Own%",
    "cost_change_event": "Price Change",
    "chance_of_playing_next_round": "Avail%",
    "news": "News",
}

# ==========================================
# 3. DATA FETCHING & PROCESSING
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
def get_league_standings(league_id):
    resp = requests.get(f"{FPL_BASE_URL}leagues-classic/{league_id}/standings/", timeout=REQUEST_TIMEOUT)
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
]
for col in numeric_cols:
    if col in players.columns:
        players[col] = pd.to_numeric(players[col], errors='coerce').fillna(0)

# chance_of_playing_next_round is null for fully fit players — default to 100, not 0
if 'chance_of_playing_next_round' in players.columns:
    players['chance_of_playing_next_round'] = pd.to_numeric(
        players['chance_of_playing_next_round'], errors='coerce'
    ).fillna(100)

# ==========================================
# 5. HELPER FUNCTIONS
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

def fixture_difficulty_score(upcoming):
    """Lower = easier run. BLANKs treated as 3, DGWs as 1.5."""
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

def get_display_df(df, cols):
    available = [c for c in cols if c in df.columns]
    return df[available].rename(columns={c: COLUMN_LABELS.get(c, c) for c in available})

def fetch_squad_picks(manager_id, gw_id):
    """Returns full picks list (with multiplier) or None on failure."""
    url = f"{FPL_BASE_URL}entry/{manager_id}/event/{gw_id}/picks/"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get('picks', [])
    except requests.RequestException:
        return None

def df_to_csv(df):
    return df.to_csv(index=False).encode('utf-8')

# ==========================================
# 6. SIDEBAR & LOGIC
# ==========================================
st.sidebar.header("Manager Settings")
my_id = st.sidebar.text_input("Manager ID", value=st.query_params.get("id", ""))
if my_id:
    st.query_params["id"] = my_id

fixture_lookahead = st.sidebar.slider("Fixture Lookahead (GWs)", min_value=3, max_value=8, value=5)

next_gw = next((e for e in data['events'] if e['is_next']), None)
curr_gw_event = next((e for e in data['events'] if e['is_current']), None)

if next_gw:
    dt = pd.to_datetime(next_gw['deadline_time']).strftime('%a %d %b %H:%M')
    st.sidebar.success(f"GW{next_gw['id']} Deadline: {dt}")

my_player_ids, my_squad, my_picks = [], pd.DataFrame(), []
if my_id and curr_gw_event:
    curr_gw_id = curr_gw_event['id']
    picks = fetch_squad_picks(my_id, curr_gw_id)
    if picks is None:
        st.sidebar.error("Could not sync squad.")
    else:
        my_picks = picks
        my_player_ids = [p['element'] for p in picks]
        my_squad = players[players['id'].isin(my_player_ids)].copy()

        # Merge multiplier (position/captain info) into my_squad
        picks_df = pd.DataFrame(picks)[['element', 'multiplier', 'position']]
        picks_df = picks_df.rename(columns={'element': 'id'})
        my_squad = my_squad.merge(picks_df, on='id', how='left')

        # --- Injury Alerts ---
        # Only flag players that FPL has explicitly flagged (non-empty news field)
        if 'chance_of_playing_next_round' in my_squad.columns and 'news' in my_squad.columns:
            flagged = my_squad[my_squad['news'].astype(str).str.strip() != '']
            unavailable = flagged[flagged['chance_of_playing_next_round'] == 0]
            injured = flagged[
                (flagged['chance_of_playing_next_round'] > 0) &
                (flagged['chance_of_playing_next_round'] < 75)
            ]

            if not unavailable.empty:
                names = ', '.join(unavailable['web_name'].tolist())
                st.sidebar.error(f"Unavailable: {names}")
            if not injured.empty:
                for _, row in injured.iterrows():
                    pct = int(row['chance_of_playing_next_round'])
                    st.sidebar.warning(f"{row['web_name']} — {pct}% chance")

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
                blank_names = ', '.join(blank_players['web_name'].tolist())
                st.sidebar.warning(f"GW{next_gw['id']} Blanks: {blank_names}")

            if blanks >= BLANK_FREE_HIT_THRESHOLD:
                st.sidebar.error(f"Free Hit Advised! ({blanks} blanks)")
            elif not my_dgw_players.empty:
                tc_cand = my_dgw_players.nlargest(1, 'form')
                if not tc_cand.empty and tc_cand.iloc[0]['form'] > FORM_TC_THRESHOLD:
                    name = tc_cand.iloc[0]['web_name']
                    st.sidebar.warning(f"Triple Captain {name} (DGW!)")
                elif len(my_dgw_players) >= DGW_BENCH_BOOST_THRESHOLD:
                    st.sidebar.success(f"Bench Boost! ({len(my_dgw_players)} DGW players)")
                else:
                    st.sidebar.info("Active DGW players. Good luck!")
            elif blanks > 0:
                st.sidebar.warning(f"{blanks} Blanks. Use FT.")
            else:
                st.sidebar.info("Save Chips. No DGW/Blanks.")

# ==========================================
# 7. MAIN DASHBOARD TABS
# ==========================================
tabs = st.tabs([
    "My Team", "GW History", "Global Scout", "Price Changes",
    "Ticker", "Player VS", "Mini-League", "Rivals", "Transfers"
])

# --- TAB 0: MY TEAM ---
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

        squad_cols = ['web_name', 'team_name', 'pos', 'price', 'form', 'total_points', 'ict_index', 'selected_by_percent']

        # Split starting XI vs bench using multiplier (0 = bench)
        starters = my_squad[my_squad['multiplier'] > 0].sort_values('position')
        bench = my_squad[my_squad['multiplier'] == 0].sort_values('position')

        st.subheader("Starting XI")
        st.dataframe(get_display_df(starters, squad_cols), use_container_width=True, hide_index=True)

        st.subheader("Bench")
        st.dataframe(get_display_df(bench, squad_cols), use_container_width=True, hide_index=True)

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
                cap_df['Score'] = (cap_df['form'] + (6 - cap_df['Diff'])).round(1)

                c_cols = st.columns(3)
                for i, (_, row) in enumerate(cap_df.nlargest(3, 'Score').iterrows()):
                    with c_cols[i]:
                        st.subheader(f"#{i+1}: {row['web_name']}")
                        st.write(f"vs **{row['Opp']}** ({opp_map.get(row['team'], {}).get('loc', 'N/A')})")
                        d = row['Diff']
                        color = "green" if d <= 2 else "orange" if d <= 3 else "red"
                        st.markdown(f"Difficulty: :{color}[Level {d}]")
                        st.metric("Cap Score", row['Score'])
            except (KeyError, ValueError):
                st.info("Fixture data pending.")
        else:
            st.info("Fixture data pending.")
    else:
        st.info("Enter your Manager ID in the sidebar to view your team.")

# --- TAB 1: GW HISTORY ---
with tabs[1]:
    st.header("Gameweek History & Points Trend")
    if my_id:
        try:
            history = get_manager_history(my_id)
            gw_history = history.get('current', [])
            if gw_history:
                hist_df = pd.DataFrame(gw_history)

                h1, h2, h3, h4 = st.columns(4)
                h1.metric("Season Total", int(hist_df['total_points'].iloc[-1]))
                h2.metric("Best GW", int(hist_df['points'].max()))
                h3.metric("Avg GW Score", round(hist_df['points'].mean(), 1))
                h4.metric("Overall Rank", f"{hist_df['overall_rank'].iloc[-1]:,}")

                # Points per GW bar + cumulative line
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=hist_df['event'],
                    y=hist_df['points'],
                    name='GW Points',
                    marker_color='#38003c',
                    opacity=0.8,
                ))
                fig.add_trace(go.Scatter(
                    x=hist_df['event'],
                    y=hist_df['total_points'],
                    name='Cumulative Pts',
                    yaxis='y2',
                    line=dict(color='#00ff85', width=2),
                ))
                fig.update_layout(
                    title="Points per Gameweek",
                    xaxis_title="Gameweek",
                    yaxis=dict(title="GW Points"),
                    yaxis2=dict(title="Cumulative Points", overlaying='y', side='right'),
                    legend=dict(orientation='h'),
                    margin=dict(l=40, r=40, t=40, b=40),
                )
                st.plotly_chart(fig, use_container_width=True)

                # Rank trend (inverted — lower rank is better)
                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(
                    x=hist_df['event'],
                    y=hist_df['overall_rank'],
                    fill='tozeroy',
                    line=dict(color='#38003c'),
                    name='Overall Rank',
                ))
                fig2.update_layout(
                    title="Overall Rank Over Season (lower = better)",
                    xaxis_title="Gameweek",
                    yaxis=dict(title="Rank", autorange='reversed'),
                    margin=dict(l=40, r=40, t=40, b=40),
                )
                st.plotly_chart(fig2, use_container_width=True)

                st.subheader("Full GW Breakdown")
                display_cols = ['event', 'points', 'total_points', 'overall_rank', 'bank', 'value', 'event_transfers', 'event_transfers_cost']
                available = [c for c in display_cols if c in hist_df.columns]
                rename = {
                    'event': 'GW', 'points': 'Pts', 'total_points': 'Total Pts',
                    'overall_rank': 'Rank', 'bank': 'Bank (0.1m)', 'value': 'Value (0.1m)',
                    'event_transfers': 'Transfers', 'event_transfers_cost': 'Transfer Cost',
                }
                st.dataframe(hist_df[available].rename(columns=rename), use_container_width=True, hide_index=True)
                st.download_button(
                    "Download History CSV",
                    df_to_csv(hist_df[available].rename(columns=rename)),
                    file_name="gw_history.csv",
                    mime="text/csv",
                )
            else:
                st.info("No gameweek history found for this manager.")
        except requests.RequestException:
            st.error("Could not load manager history. Check your Manager ID.")
    else:
        st.info("Enter your Manager ID in the sidebar.")

# --- TAB 2: GLOBAL SCOUT ---
with tabs[2]:
    st.header("Global Player Scout")
    s1, s2, s3 = st.columns(3)
    with s1:
        p_filt = st.slider("Max Price (£m)", 4.0, 15.0, 15.0, key="scout_p")
    with s2:
        po_filt = st.multiselect("Positions", options=list(pos_map.values()), default=list(pos_map.values()), key="scout_pos")
    with s3:
        t_filt = st.multiselect("Teams", options=sorted(list(team_map.values())), default=sorted(list(team_map.values())), key="scout_team")

    scout_df = players[
        (players['price'] <= p_filt) &
        (players['pos'].isin(po_filt)) &
        (players['team_name'].isin(t_filt))
    ].copy()

    scout_cols = ['web_name', 'team_name', 'pos', 'price', 'total_points', 'form', 'ict_index', 'selected_by_percent']
    sorted_scout = scout_df.sort_values('total_points', ascending=False)
    st.dataframe(get_display_df(sorted_scout, scout_cols), use_container_width=True, hide_index=True)
    st.download_button(
        "Download Scout CSV",
        df_to_csv(get_display_df(sorted_scout, scout_cols)),
        file_name="player_scout.csv",
        mime="text/csv",
    )

# --- TAB 3: PRICE CHANGES ---
with tabs[3]:
    st.header("Price Change Tracker")
    st.caption("Based on `cost_change_event` (this GW) and `cost_change_start` (vs. season start).")

    pc1, pc2 = st.columns(2)

    with pc1:
        st.subheader("Rising — This GW")
        rising = players[players['cost_change_event'] > 0].sort_values('cost_change_event', ascending=False)
        rising_cols = ['web_name', 'team_name', 'pos', 'price', 'cost_change_event', 'form', 'selected_by_percent']
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

# --- TAB 4: TICKER ---
with tabs[4]:
    st.header("Fixture Difficulty Ticker")

    sort_by_difficulty = st.toggle("Sort by Easiest Run", value=False)

    gw_cols = [f"GW+{i}" for i in range(1, fixture_lookahead + 1)]
    ticker_data = []
    for t_id, t_name in team_map.items():
        upcoming = get_upcoming_fixtures(t_id, fixtures_raw, data, num_gws=fixture_lookahead)
        score = fixture_difficulty_score(upcoming)
        ticker_data.append([t_name] + upcoming + [score])

    df_tick = pd.DataFrame(ticker_data, columns=["Team"] + gw_cols + ["Run Score"])

    if sort_by_difficulty:
        df_tick = df_tick.sort_values("Run Score")

    # Style only the fixture columns, not the score column
    styled = df_tick.drop(columns=["Run Score"]).style.map(style_ticker, subset=gw_cols[:len(df_tick.columns)-1])
    st.dataframe(styled, use_container_width=True, hide_index=True)

    if sort_by_difficulty:
        st.caption("Run Score = sum of difficulty ratings (lower = easier). Blanks=3, DGWs=1.5.")

# --- TAB 5: PLAYER VS ---
with tabs[5]:
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
            showlegend=True,
            margin=dict(l=40, r=40, t=40, b=40),
        )
        st.plotly_chart(fig_v, use_container_width=True)

        # Side-by-side stats
        st.subheader("Stats Comparison")
        compare_cols = ['web_name', 'team_name', 'pos', 'price', 'form', 'total_points', 'ict_index', 'expected_goals', 'selected_by_percent']
        p1_row = players[(players['web_name'] == p1) & (players['team_name'] == tm1)]
        p2_row = players[(players['web_name'] == p2) & (players['team_name'] == tm2)]
        compare_df = pd.concat([p1_row, p2_row])
        st.dataframe(get_display_df(compare_df, compare_cols), use_container_width=True, hide_index=True)

# --- TAB 6: MINI-LEAGUE ---
with tabs[6]:
    st.header("Mini-League Standings")
    league_id = st.text_input("Enter League ID", key="league_input")
    if league_id:
        try:
            league_data = get_league_standings(league_id)
            league_name = league_data.get('league', {}).get('name', 'League')
            st.subheader(league_name)

            results = league_data.get('standings', {}).get('results', [])
            if results:
                league_df = pd.DataFrame(results)
                display_cols_map = {
                    'rank': 'Rank',
                    'entry_name': 'Team Name',
                    'player_name': 'Manager',
                    'event_total': 'GW Score',
                    'total': 'Total Pts',
                    'last_rank': 'Last Rank',
                }
                available = [c for c in display_cols_map if c in league_df.columns]
                league_display = league_df[available].rename(columns=display_cols_map)

                # Rank movement column
                if 'last_rank' in league_df.columns and 'rank' in league_df.columns:
                    league_display['Movement'] = league_df['last_rank'] - league_df['rank']
                    league_display['Movement'] = league_display['Movement'].apply(
                        lambda x: f"+{x}" if x > 0 else str(x)
                    )

                st.dataframe(league_display, use_container_width=True, hide_index=True)
                st.download_button(
                    "Download Standings CSV",
                    df_to_csv(league_display),
                    file_name=f"{league_name}_standings.csv",
                    mime="text/csv",
                )
            else:
                st.info("No standings data found for this league.")
        except requests.RequestException:
            st.error("League not found or is private. Check the League ID.")

# --- TAB 7: RIVALS ---
with tabs[7]:
    st.header("Rival Deep-Dive")
    rival_id = st.text_input("Enter Rival Manager ID", key="riv_input")
    if my_id and rival_id and curr_gw_event:
        picks = fetch_squad_picks(rival_id, curr_gw_event['id'])
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
    elif rival_id and not curr_gw_event:
        st.warning("No current gameweek found.")
    elif not my_id:
        st.info("Enter your Manager ID in the sidebar to compare squads.")

# --- TAB 8: TRANSFERS ---
with tabs[8]:
    st.header("Transfer Optimizer")
    if not my_squad.empty:
        my_squad['efficiency'] = (my_squad['form'] + (my_squad['total_points'] / my_squad['price'])).round(1)

        num_ft = st.radio("Free Transfers Available", options=[1, 2, "Wildcard"], horizontal=True)
        n_transfers = 2 if num_ft == "Wildcard" else int(num_ft)

        sorted_squad = my_squad.sort_values('efficiency')
        candidates = sorted_squad.head(n_transfers)

        st.subheader("Drop Candidates")
        drop_cols = ['web_name', 'team_name', 'pos', 'price', 'form', 'efficiency', 'selected_by_percent']
        st.dataframe(get_display_df(candidates, drop_cols), use_container_width=True, hide_index=True)

        st.subheader("Recommended Replacements (per candidate)")
        for _, worst in candidates.iterrows():
            with st.expander(f"Replace {worst['web_name']} (£{worst['price']}m | Eff: {worst['efficiency']})"):
                bud = worst['price'] + TRANSFER_BUDGET_BUFFER
                if num_ft == "Wildcard":
                    bud = worst['price'] + 2.0  # wider budget window for wildcard
                targets = players[
                    (players['pos'] == worst['pos']) &
                    (players['price'] <= bud) &
                    (~players['id'].isin(my_player_ids))
                ].nlargest(TRANSFER_TARGET_COUNT, 'ict_index')

                t_cols = ['web_name', 'team_name', 'price', 'form', 'ict_index', 'expected_goals', 'total_points', 'selected_by_percent']
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
