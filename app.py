import streamlit as st
import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go

# ==========================================
# 1. PAGE CONFIGURATION & SURGICAL CSS
# ==========================================
st.set_page_config(page_title="FPL Elite Dashboard", layout="wide")

st.markdown("""
    <style>
    /* 1. FIX INVISIBLE LABELS - Targeted specifically at Metric Widgets */
    [data-testid="stMetricLabel"] div, [data-testid="stMetricLabel"] p {
        color: #111827 !important;
        font-weight: 700 !important;
    }

    /* 2. FIX INVISIBLE HEADERS - Targeted to avoid breaking colored text */
    .stMarkdown h3 {
        color: #111827 !important;
    }

    /* 3. ENSURE METRIC VALUES ARE DARK */
    [data-testid="stMetricValue"] div {
        color: #000000 !important;
    }

    /* 4. CARD STYLING - Applied ONLY to metrics to preserve Chart visibility */
    [data-testid="stMetric"] {
        background-color: #ffffff !important;
        border: 1px solid #e2e8f0 !important;
        border-radius: 10px !important;
        padding: 10px !important;
    }
    
    /* 5. SIDEBAR VISIBILITY */
    section[data-testid="stSidebar"] .stMarkdown p, 
    section[data-testid="stSidebar"] .stMarkdown h3 {
        color: #ffffff !important;
    }
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 2. DATA FETCHING & PROCESSING
# ==========================================
@st.cache_data(ttl=3600)
def get_fpl_data():
    base_url = "https://fantasy.premierleague.com/api/"
    bootstrap = requests.get(f"{base_url}bootstrap-static/").json()
    fixtures = requests.get(f"{base_url}fixtures/").json()
    return bootstrap, fixtures

data, fixtures_raw = get_fpl_data()
players = pd.DataFrame(data['elements'])
teams = pd.DataFrame(data['teams'])
team_map = dict(zip(teams['id'], teams['name']))
pos_map = dict(zip([t['id'] for t in data['element_types']], [t['singular_name_short'] for t in data['element_types']]))

# 4. DATA CLEANING
players['team_name'] = players['team'].map(team_map)
players['pos'] = players['element_type'].map(pos_map)
players['price'] = players['now_cost'] / 10
numeric_cols = ['expected_goals', 'expected_assists', 'ict_index', 'form', 'total_points', 'minutes']
for col in numeric_cols:
    players[col] = pd.to_numeric(players[col], errors='coerce').fillna(0)

# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================
def get_upcoming_fixtures(team_id, fixtures, data, num_gws=5):
    upcoming = []
    try:
        curr_gw = next(e['id'] for e in data['events'] if e['is_current'])
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
            else: upcoming.append("BLANK")
    except: pass
    return upcoming

def style_ticker(val):
    if pd.isna(val) or '|' not in str(val): return ''
    if "DGW" in str(val): return 'background-color: #38003c; color: white; font-weight: bold;'
    diff = int(str(val).split('|')[-1].strip())
    colors = {1: '#00753e', 2: '#01fc7a', 3: '#e7e7e7', 4: '#ff1751', 5: '#80072d'}
    text = 'white' if diff in [1, 4, 5] else 'black'
    return f'background-color: {colors.get(diff, "")}; color: {text}; font-weight: bold;'

def get_display_df(df, cols):
    labels = {
        "web_name": "Player", "team_name": "Team", "pos": "Pos", "price": "£m", 
        "total_points": "Pts", "form": "Form", "ict_index": "ICT", 
        "expected_goals": "xG", "efficiency": "Eff Score"
    }
    return df[cols].rename(columns={c: labels.get(c, c) for c in cols})

# ==========================================
# 4. SIDEBAR & LOGIC
# ==========================================
st.sidebar.header("👤 Manager Settings")
my_id = st.sidebar.text_input("Manager ID", value=st.query_params.get("id", "587574"))
if my_id: st.query_params["id"] = my_id

next_gw = next((e for e in data['events'] if e['is_next']), None)
if next_gw:
    dt = pd.to_datetime(next_gw['deadline_time']).strftime('%a %d %b %H:%M')
    st.sidebar.success(f"⏳ GW{next_gw['id']} Deadline: {dt}")

my_player_ids, my_squad = [], pd.DataFrame()
if my_id:
    try:
        curr_gw_id = next(e['id'] for e in data['events'] if e['is_current'])
        r = requests.get(f"https://fantasy.premierleague.com/api/entry/{my_id}/event/{curr_gw_id}/picks/").json()
        my_player_ids = [p['element'] for p in r['picks']]
        my_squad = players[players['id'].isin(my_player_ids)].copy()

        st.sidebar.markdown("---")
        st.sidebar.subheader("💡 Chip Strategy")
        
        # LOGIC: DGW & BLANKS
        gw_fixtures = [f for f in fixtures_raw if f['event'] == next_gw['id']]
        all_teams_playing = [f['team_h'] for f in gw_fixtures] + [f['team_a'] for f in gw_fixtures]
        team_counts = pd.Series(all_teams_playing).value_counts()
        
        dgw_teams = team_counts[team_counts > 1].index.tolist()
        my_dgw_players = my_squad[my_squad['team'].isin(dgw_teams)]
        
        active_teams = set(team_counts.index)
        blanks = 11 - len(my_squad[my_squad['team'].isin(active_teams)])

        # CHIP RECOMMENDATION ENGINE
        if blanks >= 4:
            st.sidebar.error(f"🔥 Free Hit Advised! ({blanks} blanks)")
        elif not my_dgw_players.empty:
            # Check for TC candidate in DGW
            tc_cand = my_dgw_players.nlargest(1, 'form')
            if not tc_cand.empty and tc_cand.iloc[0]['form'] > 5.0:
                name = tc_cand.iloc[0]['web_name']
                st.sidebar.warning(f"👑 Triple Captain {name} (DGW!)")
            # Check for BB in DGW
            elif len(my_dgw_players) >= 3:
                st.sidebar.success(f"🚀 Bench Boost! ({len(my_dgw_players)} DGW players)")
            else:
                st.sidebar.info("✅ Active DGW players. Good luck!")
        elif blanks > 0:
            st.sidebar.warning(f"⚠️ {blanks} Blanks. Use FT.")
        else:
            st.sidebar.info("✅ Save Chips. No DGW/Blanks.")
            
    except: st.sidebar.error("Could not sync squad.")

# ==========================================
# 5. MAIN DASHBOARD TABS
# ==========================================
tabs = st.tabs(["🏠 My Team", "📊 Global Scout", "📅 Ticker", "⚔️ Player VS", "🛡️ Rivals", "🔄 Transfers"])

# --- TAB 0: MY TEAM ---
with tabs[0]: 
    if not my_squad.empty:
        st.header("🏆 Squad Performance")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Pts", int(my_squad['total_points'].sum()))
        m2.metric("Squad xG", round(my_squad['expected_goals'].sum(), 2))
        m3.metric("Avg Form", round(my_squad['form'].mean(), 1))
        m4.metric("Squad Value", f"£{my_squad['price'].sum():.1f}m")
        
        st.dataframe(get_display_df(my_squad, ['web_name', 'team_name', 'pos', 'price', 'form', 'total_points', 'ict_index']), use_container_width=True, hide_index=True)

        st.markdown("---")
        st.header("🧑‍✈️ Captaincy Predictor")
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
            for i, (idx, row) in enumerate(cap_df.nlargest(3, 'Score').iterrows()):
                with c_cols[i]:
                    st.subheader(f"#{i+1}: {row['web_name']}")
                    st.write(f"vs **{row['Opp']}** ({opp_map.get(row['team'], {}).get('loc', 'N/A')})")
                    d = row['Diff']
                    color = "green" if d <= 2 else "orange" if d <= 3 else "red"
                    st.markdown(f"Difficulty: :{color}[Level {d}]")
                    st.metric("Cap Score", row['Score'])
        except: st.info("Fixture data pending.")

# --- TAB 1: GLOBAL SCOUT ---
with tabs[1]:
    st.header("🔍 Global Player Scout")
    s1, s2, s3 = st.columns(3)
    with s1: p_filt = st.slider("Max Price (£m)", 4.0, 15.0, 15.0, key="scout_p")
    with s2: po_filt = st.multiselect("Positions", options=list(pos_map.values()), default=list(pos_map.values()), key="scout_pos")
    with s3: t_filt = st.multiselect("Teams", options=sorted(list(team_map.values())), default=sorted(list(team_map.values())), key="scout_team")
    
    scout_df = players[(players['price'] <= p_filt) & (players['pos'].isin(po_filt)) & (players['team_name'].isin(t_filt))].copy()
    st.dataframe(get_display_df(scout_df.sort_values('total_points', ascending=False), ['web_name', 'team_name', 'pos', 'price', 'total_points', 'form', 'ict_index']), use_container_width=True, hide_index=True)

# --- TAB 2: TICKER ---
with tabs[2]:
    st.header("📅 5-Week Ticker")
    ticker_data = [[t_name] + get_upcoming_fixtures(t_id, fixtures_raw, data) for t_id, t_name in team_map.items()]
    df_tick = pd.DataFrame(ticker_data, columns=["Team", "GW+1", "GW+2", "GW+3", "GW+4", "GW+5"])
    st.dataframe(df_tick.style.applymap(style_ticker, subset=df_tick.columns[1:]), use_container_width=True, hide_index=True)

# --- TAB 3: PLAYER VS (FIXED VISIBILITY) ---
with tabs[3]:
    st.header("⚔️ Player VS Radar")
    v1, v2 = st.columns(2)
    with v1:
        tm1 = st.selectbox("Team 1", sorted(teams['name'].unique()), key="v1_tm")
        p1 = st.selectbox("Player 1", sorted(players[players['team_name']==tm1]['web_name']), key="v1_p")
    with v2:
        tm2 = st.selectbox("Team 2", sorted(teams['name'].unique()), key="v2_tm", index=1)
        p2 = st.selectbox("Player 2", sorted(players[players['team_name']==tm2]['web_name']), key="v2_p")
    
    rad_mets = ['form', 'expected_goals', 'ict_index', 'total_points']
    def make_rad(n, t):
        p_row = players[(players['web_name']==n) & (players['team_name']==t)].iloc[0]
        return [p_row[m] for m in rad_mets]
    
    fig_v = go.Figure()
    fig_v.add_trace(go.Scatterpolar(r=make_rad(p1, tm1), theta=rad_mets, fill='toself', name=p1, line_color='#38003c'))
    fig_v.add_trace(go.Scatterpolar(r=make_rad(p2, tm2), theta=rad_mets, fill='toself', name=p2, line_color='#00ff85'))
    fig_v.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, players[rad_mets].max().max()])), 
        showlegend=True,
        margin=dict(l=40, r=40, t=40, b=40)
    )
    st.plotly_chart(fig_v, use_container_width=True)

# --- TAB 4: RIVALS (DEEP DIVE) ---
with tabs[4]:
    st.header("🛡️ Rival Deep-Dive")
    rival_id = st.text_input("Enter Rival Manager ID", key="riv_input")
    if my_id and rival_id:
        try:
            curr_gw_id = next(e['id'] for e in data['events'] if e['is_current'])
            riv_r = requests.get(f"https://fantasy.premierleague.com/api/entry/{rival_id}/event/{curr_gw_id}/picks/").json()
            riv_ids = [p['element'] for p in riv_r['picks']]
            my_set, riv_set = set(my_player_ids), set(riv_ids)
            
            # Detailed columns for analysis
            riv_cols = ['web_name', 'team_name', 'price', 'total_points', 'form', 'ict_index', 'expected_goals']
            
            st.subheader("🛡️ Shield (Shared Assets)")
            st.dataframe(get_display_df(players[players['id'].isin(my_set & riv_set)], riv_cols), use_container_width=True, hide_index=True)
            
            st.subheader("🗡️ Your Sword (Differentials)")
            st.dataframe(get_display_df(players[players['id'].isin(my_set - riv_set)], riv_cols), use_container_width=True, hide_index=True)
            
            st.subheader("⚠️ Danger (Rival Differentials)")
            st.dataframe(get_display_df(players[players['id'].isin(riv_set - my_set)], riv_cols), use_container_width=True, hide_index=True)
        except: st.error("Rival ID not found.")

# --- TAB 5: TRANSFERS (ADDED DETAIL) ---
with tabs[5]:
    st.header("🔄 Transfer Optimizer")
    if not my_squad.empty:
        # Simple efficiency metric: Form + (Points per Million)
        my_squad['efficiency'] = (my_squad['form'] + (my_squad['total_points']/my_squad['price'])).round(1)
        worst = my_squad.sort_values('efficiency').iloc[0]
        
        tc1, tc2 = st.columns([1, 2])
        with tc1:
            st.subheader("🔴 Drop Candidate")
            st.metric(worst['web_name'], f"Eff: {worst['efficiency']}")
            st.write(f"Price: £{worst['price']}m | Form: {worst['form']}")
        
        with tc2:
            st.subheader("🟢 Recommended Replacements")
            bud = worst['price'] + 0.5
            targets = players[(players['pos'] == worst['pos']) & (players['price'] <= bud) & (~players['id'].isin(my_player_ids))].nlargest(8, 'ict_index')
            
            # Expanded columns for better decision making
            t_cols = ['web_name', 'team_name', 'price', 'form', 'ict_index', 'expected_goals', 'total_points']
            st.dataframe(get_display_df(targets, t_cols), use_container_width=True, hide_index=True)