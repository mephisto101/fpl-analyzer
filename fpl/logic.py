from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class FixtureOpponent:
    opp_team_id: int
    is_home: bool
    difficulty: int
    kickoff_time: str | None = None


@dataclass(frozen=True)
class FixtureCell:
    """
    Structured representation of a team's fixture(s) in a given GW.

    kind:
      - single: one fixture
      - dgw: multiple fixtures
      - blank: no fixture
      - na: data not available
    """

    kind: str
    opponents: tuple[FixtureOpponent, ...] = ()

    @property
    def primary_difficulty(self) -> int | None:
        if not self.opponents:
            return None
        # For DGW, prefer average difficulty for sorting/scoring.
        return int(round(sum(o.difficulty for o in self.opponents) / len(self.opponents)))


def _current_gw_id(data: dict[str, Any]) -> int:
    return next(e["id"] for e in data["events"] if e["is_current"])


def get_upcoming_fixture_cells(
    *,
    team_id: int,
    fixtures: list[dict[str, Any]],
    data: dict[str, Any],
    num_gws: int = 5,
) -> list[FixtureCell]:
    """
    Return structured fixtures for the next `num_gws` gameweeks after the current GW.
    """
    out: list[FixtureCell] = []
    try:
        curr_gw = _current_gw_id(data)
        for gw in range(curr_gw + 1, curr_gw + num_gws + 1):
            f_list = [
                f
                for f in fixtures
                if f.get("event") == gw and (f.get("team_h") == team_id or f.get("team_a") == team_id)
            ]

            if not f_list:
                out.append(FixtureCell(kind="blank"))
                continue

            opponents: list[FixtureOpponent] = []
            for f in f_list:
                is_home = f["team_h"] == team_id
                opp_id = f["team_a"] if is_home else f["team_h"]
                diff = f["team_h_difficulty"] if is_home else f["team_a_difficulty"]
                opponents.append(
                    FixtureOpponent(
                        opp_team_id=int(opp_id),
                        is_home=bool(is_home),
                        difficulty=int(diff),
                        kickoff_time=f.get("kickoff_time"),
                    )
                )

            kind = "single" if len(opponents) == 1 else "dgw"
            out.append(FixtureCell(kind=kind, opponents=tuple(opponents)))
    except (StopIteration, KeyError, TypeError, ValueError):
        return [FixtureCell(kind="na")] * num_gws

    return out


def format_fixture_cell(
    cell: FixtureCell,
    *,
    team_name_map: dict[int, str] | None = None,
    team_short_name_map: dict[int, str] | None = None,
    include_dgw_opponents: bool = True,
) -> str:
    if cell.kind == "na":
        return "N/A"
    if cell.kind == "blank":
        return "BLANK"
    if cell.kind == "dgw" and (not include_dgw_opponents or not cell.opponents):
        return f"DGW ({len(cell.opponents)})"

    def _team_label(team_id: int) -> str:
        if team_short_name_map and team_id in team_short_name_map:
            return team_short_name_map[team_id]
        if team_name_map and team_id in team_name_map:
            return team_name_map[team_id][:3]
        return str(team_id)

    if cell.kind == "single":
        o = cell.opponents[0]
        return f"{_team_label(o.opp_team_id)} ({'H' if o.is_home else 'A'}) | {o.difficulty}"

    # DGW formatted as "OPP (H) | d + OPP (A) | d"
    parts = [
        f"{_team_label(o.opp_team_id)} ({'H' if o.is_home else 'A'}) | {o.difficulty}"
        for o in cell.opponents
    ]
    return " + ".join(parts) if parts else "DGW (0)"


def get_upcoming_fixtures(
    *,
    team_id: int,
    fixtures: list[dict[str, Any]],
    data: dict[str, Any],
    team_map: dict[int, str],
    num_gws: int = 5,
) -> list[str]:
    """
    Backward-compatible string fixtures used by the current Streamlit UI/tests.
    """
    cells = get_upcoming_fixture_cells(team_id=team_id, fixtures=fixtures, data=data, num_gws=num_gws)
    # Preserve the previous behavior for DGW: "DGW (n)" rather than listing opponents.
    return [
        format_fixture_cell(c, team_name_map=team_map, include_dgw_opponents=False)  # type: ignore[arg-type]
        if c.kind != "single"
        else format_fixture_cell(c, team_name_map=team_map, include_dgw_opponents=False)
        for c in cells
    ]


def style_ticker(val: Any) -> str:
    # Supports FixtureCell, old string format, and empty cells.
    if isinstance(val, FixtureCell):
        if val.kind == "dgw":
            return "background-color: #38003c; color: white; font-weight: bold;"
        if val.kind in ("blank", "na"):
            return "background-color: #f3f4f6; color: #111827; font-weight: 600;"
        diff = val.primary_difficulty
        if diff is None:
            return ""
        colors = {1: "#00753e", 2: "#01fc7a", 3: "#e7e7e7", 4: "#ff1751", 5: "#80072d"}
        text = "white" if diff in [1, 4, 5] else "black"
        return f"background-color: {colors.get(int(diff), '')}; color: {text}; font-weight: bold;"

    if pd.isna(val):
        return ""

    s = str(val)
    if "DGW" in s:
        return "background-color: #38003c; color: white; font-weight: bold;"

    if s in ("BLANK", "N/A"):
        return "background-color: #f3f4f6; color: #111827; font-weight: 600;"

    if "|" not in s:
        return ""

    # For DGW formatted as "X | d + Y | d", use average difficulty.
    try:
        diffs = [int(p.split("|")[-1].strip()) for p in s.split("+") if "|" in p]
        diff = int(round(sum(diffs) / len(diffs))) if diffs else int(s.split("|")[-1].strip())
    except ValueError:
        return ""

    colors = {1: "#00753e", 2: "#01fc7a", 3: "#e7e7e7", 4: "#ff1751", 5: "#80072d"}
    text = "white" if diff in [1, 4, 5] else "black"
    return f"background-color: {colors.get(diff, '')}; color: {text}; font-weight: bold;"


def optimize_starting_xi(
    squad: pd.DataFrame,
    *,
    score_col: str,
    pos_col: str = "pos",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Brute-force best XI from a 15-man squad under FPL formation constraints.

    Returns (starting_xi_df, bench_df) both sorted by score desc.

    Assumptions:
      - squad has exactly 15 rows
      - pos values are short names: "GKP", "DEF", "MID", "FWD"
    """
    if squad.empty:
        return squad.copy(), squad.copy()

    df = squad.copy().reset_index(drop=True)
    df["_score"] = pd.to_numeric(df[score_col], errors="coerce").fillna(0.0)
    df["_pos"] = df[pos_col].astype(str)

    gk_idx = df.index[df["_pos"] == "GKP"].tolist()
    def_idx = df.index[df["_pos"] == "DEF"].tolist()
    mid_idx = df.index[df["_pos"] == "MID"].tolist()
    fwd_idx = df.index[df["_pos"] == "FWD"].tolist()

    # We must pick: 1 GK and 10 outfield with constraints:
    # DEF 3-5, MID 2-5, FWD 1-3
    best_score = float("-inf")
    best_idxs: list[int] = []

    import itertools

    for gk in itertools.combinations(gk_idx, 1):
        for d in range(3, 6):
            for m in range(2, 6):
                for f in range(1, 4):
                    if d + m + f != 10:
                        continue
                    for defs in itertools.combinations(def_idx, d):
                        for mids in itertools.combinations(mid_idx, m):
                            for fwds in itertools.combinations(fwd_idx, f):
                                idxs = list(gk + defs + mids + fwds)
                                s = float(df.loc[idxs, "_score"].sum())
                                if s > best_score:
                                    best_score = s
                                    best_idxs = idxs

    xi = df.loc[best_idxs].sort_values("_score", ascending=False).drop(columns=["_score", "_pos"])
    bench = df.drop(index=best_idxs).sort_values("_score", ascending=False).drop(columns=["_score", "_pos"])
    return xi.reset_index(drop=True), bench.reset_index(drop=True)


# ===========================
# Phase 1 helpers (Roadmap)
# ===========================


def captain_reason_breakdown(
    row: pd.Series,
    *,
    max_ict: float,
    home_captain_bonus: float,
    weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    """
    Return an interpretable breakdown of the captain score for a player row.

    Expected row fields:
      - form, ict_index, Diff (fixture difficulty 1..5 where lower is easier), Loc ('H'/'A')
      - play_prob (0..1) optional, rotation_risk optional, chance_of_playing_next_round optional
    """
    w = weights or {"form": 0.45, "ict": 0.30, "fixture": 0.20, "home": 0.05}
    form = float(pd.to_numeric(row.get("form", 0), errors="coerce") or 0.0)
    ict = float(pd.to_numeric(row.get("ict_index", 0), errors="coerce") or 0.0)
    diff = float(pd.to_numeric(row.get("Diff", 3), errors="coerce") or 3.0)
    loc = str(row.get("Loc", "A"))

    ict_norm = (ict / (max_ict or 1.0)) * 10.0
    fixture_score = (6.0 - diff)
    home_score = home_captain_bonus if loc == "H" else 0.0

    parts = [
        ("Fixture", w["fixture"] * fixture_score, f"Difficulty {int(diff)} ({loc})"),
        ("Form", w["form"] * form, f"Form {form:.1f}"),
        ("Attacking (ICT)", w["ict"] * ict_norm, f"ICT {ict:.1f} → norm {ict_norm:.1f}/10"),
        ("Home bonus", w["home"] * home_score, "Home" if loc == "H" else "Away"),
    ]

    df = pd.DataFrame(parts, columns=["Reason", "Contribution", "Notes"])
    df["Contribution"] = df["Contribution"].round(2)
    df = df.sort_values("Contribution", ascending=False).reset_index(drop=True)
    df["Share"] = (df["Contribution"] / (df["Contribution"].sum() or 1.0) * 100).round(0).astype(int)
    return df


def captain_confidence(
    row: pd.Series,
    *,
    high_cutoff: float = 0.80,
    med_cutoff: float = 0.60,
) -> tuple[str, list[str]]:
    """
    Convert minutes/availability proxies into (tier, flags).
    """
    flags: list[str] = []
    play_prob = float(pd.to_numeric(row.get("play_prob", 1.0), errors="coerce") or 1.0)
    chance = row.get("chance_of_playing_next_round", None)
    rotation_risk = str(row.get("rotation_risk", "")).strip()
    news = str(row.get("news", "")).strip()

    if isinstance(chance, (int, float)) and float(chance) < 75:
        flags.append(f"Availability {int(chance)}%")
    if rotation_risk and rotation_risk.lower() != "ok":
        flags.append(f"Rotation risk: {rotation_risk}")
    if news and news.lower() not in ("nan", "none"):
        flags.append("Flagged news")

    tier = "High"
    if play_prob < med_cutoff:
        tier = "Low"
    elif play_prob < high_cutoff:
        tier = "Medium"

    # If we have any red flags, cap the tier at Medium unless play_prob is extremely high.
    if flags and tier == "High" and play_prob < 0.92:
        tier = "Medium"

    return tier, flags


def why_not_notes(
    *,
    candidate: pd.Series,
    winner: pd.Series,
) -> list[str]:
    """
    Generate short "why not" notes for near-miss captain candidates.
    """
    notes: list[str] = []
    cand_pp = float(pd.to_numeric(candidate.get("play_prob", 1.0), errors="coerce") or 1.0)
    win_pp = float(pd.to_numeric(winner.get("play_prob", 1.0), errors="coerce") or 1.0)
    cand_diff = float(pd.to_numeric(candidate.get("Diff", 3), errors="coerce") or 3.0)
    win_diff = float(pd.to_numeric(winner.get("Diff", 3), errors="coerce") or 3.0)

    if cand_pp + 0.10 < win_pp:
        notes.append("Lower minutes confidence")
    if cand_diff > win_diff + 1:
        notes.append("Tougher fixture")

    # If candidate is away and winner is home, mention it.
    cand_loc = str(candidate.get("Loc", "A"))
    win_loc = str(winner.get("Loc", "A"))
    if cand_loc != "H" and win_loc == "H":
        notes.append("Away vs winner at home")

    # If score close but projection lower, mention that.
    cand_proj = float(pd.to_numeric(candidate.get("proj_pts", 0), errors="coerce") or 0.0)
    win_proj = float(pd.to_numeric(winner.get("proj_pts", 0), errors="coerce") or 0.0)
    if cand_proj + 0.5 < win_proj:
        notes.append("Lower short-horizon projection")

    return notes[:3]


def build_one_click_plan_markdown(
    *,
    gw_id: int | None,
    captain: pd.Series | None,
    vice: pd.Series | None,
    xi_df: pd.DataFrame,
    bench_df: pd.DataFrame,
    chip_note: str | None = None,
    transfer_idea: str | None = None,
    risks: list[str] | None = None,
) -> str:
    def _name(s: pd.Series | None) -> str:
        if s is None or s.empty:
            return "—"
        return str(s.get("web_name", "—"))

    lines: list[str] = []
    lines.append(f"# Weekly Plan{' — GW' + str(gw_id) if gw_id else ''}")
    lines.append("")
    lines.append(f"**Captain:** {_name(captain)}")
    lines.append(f"**Vice-captain:** {_name(vice)}")
    lines.append("")
    lines.append("## Starting XI")
    for n in xi_df.get("web_name", pd.Series(dtype=str)).tolist():
        lines.append(f"- {n}")
    lines.append("")
    lines.append("## Bench order")
    for n in bench_df.get("web_name", pd.Series(dtype=str)).tolist():
        lines.append(f"- {n}")
    lines.append("")
    if transfer_idea:
        lines.append("## Transfer idea")
        lines.append(f"- {transfer_idea}")
        lines.append("")
    if chip_note:
        lines.append("## Chip note")
        lines.append(f"- {chip_note}")
        lines.append("")
    if risks:
        lines.append("## Key risks")
        for r in risks:
            lines.append(f"- {r}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def eo_risk_panel(
    *,
    players: pd.DataFrame,
    my_squad_ids: set[int],
    captain_id: int | None,
    template_top_n: int = 30,
    differential_own_cutoff: float = 10.0,
) -> dict[str, Any]:
    """
    Lightweight EO/template risk proxy from ownership + a captaincy assumption.

    Returns a dict with:
      - template_df: top owned players with in_squad flag
      - threats_df: high owned not owned
      - differentials_df: low owned owned with upside
      - shield_score / attack_score (0..100-ish)
    """
    df = players.copy()
    df["selected_by_percent"] = pd.to_numeric(df.get("selected_by_percent", 0), errors="coerce").fillna(0.0)
    template = df.sort_values("selected_by_percent", ascending=False).head(template_top_n).copy()
    template["in_squad"] = template["id"].astype(int).isin(my_squad_ids)

    # Threat: high owned not owned, weighted by projection if present.
    if "proj_pts" in df.columns:
        template["threat_score"] = (template["selected_by_percent"] * pd.to_numeric(template["proj_pts"], errors="coerce").fillna(0.0)).round(1)
    else:
        template["threat_score"] = template["selected_by_percent"].round(1)

    threats = template[~template["in_squad"]].sort_values("threat_score", ascending=False).head(10).copy()

    # Shield score: share of template ownership you "cover" (captain adds extra coverage).
    cover = template[template["in_squad"]]["selected_by_percent"].sum()
    total = template["selected_by_percent"].sum() or 1.0
    cap_bonus = 0.0
    if captain_id is not None:
        cap_row = template[template["id"].astype(int) == int(captain_id)]
        if not cap_row.empty:
            cap_bonus = float(cap_row.iloc[0]["selected_by_percent"]) * 0.5  # extra EO from captaincy
    shield_score = round((cover + cap_bonus) / total * 100.0, 1)

    # Attack score: how much upside you have in low-owned players (if proj_pts exists).
    owned = df[df["id"].astype(int).isin(my_squad_ids)].copy()
    owned_low = owned[owned["selected_by_percent"] <= differential_own_cutoff].copy()
    if "proj_pts" in owned_low.columns:
        owned_low["attack_contrib"] = (
            (differential_own_cutoff - owned_low["selected_by_percent"]).clip(lower=0.0)
            * pd.to_numeric(owned_low["proj_pts"], errors="coerce").fillna(0.0)
        )
        attack_score = float(owned_low["attack_contrib"].sum())
        # Normalize to a 0..100-ish scale for display.
        attack_score = round(min(100.0, attack_score / 2.5), 1)
    else:
        attack_score = round(min(100.0, float(len(owned_low)) * 5.0), 1)

    if "proj_pts" in owned.columns:
        owned_low = owned_low.sort_values("proj_pts", ascending=False)
    else:
        owned_low = owned_low.sort_values("selected_by_percent", ascending=True)

    return {
        "template_df": template,
        "threats_df": threats,
        "differentials_df": owned_low.head(10),
        "shield_score": shield_score,
        "attack_score": attack_score,
    }


def chip_lookahead(
    *,
    team_ids: list[int],
    fixtures: list[dict[str, Any]],
    data: dict[str, Any],
    horizon_gws: int = 8,
) -> pd.DataFrame:
    """
    Summarize upcoming blank/DGW landscape for a set of team ids (e.g. your squad's teams).
    Returns a dataframe with one row per GW+N.
    """
    rows: list[dict[str, object]] = []
    try:
        curr_gw = _current_gw_id(data)
        for i in range(1, horizon_gws + 1):
            gw = curr_gw + i
            active_teams: set[int] = set()
            dgw_teams: set[int] = set()

            gw_fixtures = [f for f in fixtures if f.get("event") == gw]
            counts: dict[int, int] = {}
            for f in gw_fixtures:
                try:
                    h = int(f["team_h"])
                    a = int(f["team_a"])
                except Exception:
                    continue
                counts[h] = counts.get(h, 0) + 1
                counts[a] = counts.get(a, 0) + 1
                active_teams.add(h)
                active_teams.add(a)

            for t, c in counts.items():
                if c > 1:
                    dgw_teams.add(t)

            blanks = sum(1 for t in team_ids if int(t) not in active_teams)
            dgws = sum(1 for t in team_ids if int(t) in dgw_teams)

            rows.append(
                {
                    "GW": gw,
                    "Blanks (squad)": blanks,
                    "DGW players (squad)": dgws,
                    "Fixtures total": len(gw_fixtures),
                    "DGW teams": len(dgw_teams),
                }
            )
    except Exception:
        return pd.DataFrame(columns=["GW", "Blanks (squad)", "DGW players (squad)", "Fixtures total", "DGW teams"])

    return pd.DataFrame(rows)

