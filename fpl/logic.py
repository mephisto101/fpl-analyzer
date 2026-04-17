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


def build_captaincy_matrix(
    squad: pd.DataFrame,
    *,
    max_ict: float,
    home_bonus: float = 0.5,
) -> pd.DataFrame:
    """
    Build a ranked captaincy matrix with confidence and reason codes.

    Expected columns in `squad`:
      - web_name, form, ict_index, Diff, Loc
    Optional columns:
      - proj_pts, play_prob, selected_by_percent, avg_minutes
    """
    if squad.empty:
        return squad.copy()

    cap = squad.copy()
    safe_max_ict = max(float(max_ict or 1.0), 1.0)

    cap["form"] = pd.to_numeric(cap.get("form", 0), errors="coerce").fillna(0.0)
    cap["ict_index"] = pd.to_numeric(cap.get("ict_index", 0), errors="coerce").fillna(0.0)
    cap["Diff"] = pd.to_numeric(cap.get("Diff", 3), errors="coerce").fillna(3.0)
    cap["play_prob"] = pd.to_numeric(cap.get("play_prob", 0.75), errors="coerce").fillna(0.75).clip(0, 1)
    cap["proj_pts"] = pd.to_numeric(cap.get("proj_pts", 0), errors="coerce").fillna(0.0)
    cap["selected_by_percent"] = pd.to_numeric(
        cap.get("selected_by_percent", 0), errors="coerce"
    ).fillna(0.0)
    cap["avg_minutes"] = pd.to_numeric(cap.get("avg_minutes", 90), errors="coerce").fillna(90.0)

    cap["ict_norm"] = (cap["ict_index"] / safe_max_ict * 10).round(1)
    cap["form_component"] = cap["form"] * 0.45
    cap["ict_component"] = cap["ict_norm"] * 0.30
    cap["fixture_component"] = (6 - cap["Diff"]) * 0.20
    cap["home_component"] = cap["Loc"].astype(str).eq("H").astype(float) * float(home_bonus)

    cap["Score"] = (
        cap["form_component"] + cap["ict_component"] + cap["fixture_component"] + cap["home_component"]
    ).round(2)

    confidence = (
        cap["play_prob"] * 100
        + cap["Diff"].apply(lambda d: 6 if d <= 2 else (-6 if d >= 4 else 0))
        + cap["avg_minutes"].apply(lambda m: -12 if m < 55 else (4 if m >= 75 else 0))
    )
    cap["Confidence"] = confidence.round(0).clip(0, 99).astype(int)
    cap["Confidence Tier"] = cap["Confidence"].apply(
        lambda c: "High" if c >= 80 else ("Medium" if c >= 60 else "Low")
    )

    cap["Captain Rank Score"] = (cap["Score"] * 0.6 + cap["proj_pts"] * 0.4).round(2)

    def _reasons(row: pd.Series) -> str:
        parts: list[str] = []
        if float(row.get("form", 0)) >= 6:
            parts.append("FORM+")
        elif float(row.get("form", 0)) < 3:
            parts.append("FORM-")
        if float(row.get("Diff", 3)) <= 2:
            parts.append("FIXTURE+")
        elif float(row.get("Diff", 3)) >= 4:
            parts.append("FIXTURE-")
        if str(row.get("Loc", "A")) == "H":
            parts.append("HOME")
        if float(row.get("play_prob", 0.75)) < 0.75 or float(row.get("avg_minutes", 90)) < 55:
            parts.append("MINS?")
        own = float(row.get("selected_by_percent", 0))
        if own >= 25:
            parts.append("EO-SHIELD")
        elif own <= 10:
            parts.append("DIFF-UPSIDE")
        return ", ".join(parts) if parts else "BALANCED"

    def _why_not(row: pd.Series) -> str:
        notes: list[str] = []
        if float(row.get("play_prob", 0.75)) < 0.75:
            notes.append("minutes risk")
        if float(row.get("Diff", 3)) >= 4:
            notes.append("tough fixture")
        if float(row.get("form", 0)) < 3:
            notes.append("low recent form")
        if not notes:
            return "Narrowly behind the top pick on blended rank score."
        return "; ".join(notes).capitalize() + "."

    cap["Reason Codes"] = cap.apply(_reasons, axis=1)
    cap["Why Not"] = cap.apply(_why_not, axis=1)
    cap["Tier"] = cap["Score"].apply(lambda s: "A — Strong" if s > 4 else ("B — Solid" if s >= 2.5 else "C — Risky"))

    return cap.sort_values("Captain Rank Score", ascending=False).reset_index(drop=True)


def add_estimated_effective_ownership(
    players: pd.DataFrame,
    *,
    captain_ids: set[int] | None = None,
) -> pd.DataFrame:
    """
    Add estimated EO and attack index.

    Estimated EO ~= ownership * minutes confidence; captain EO is doubled.
    """
    if players.empty:
        return players.copy()

    out = players.copy()
    out["selected_by_percent"] = pd.to_numeric(
        out.get("selected_by_percent", 0), errors="coerce"
    ).fillna(0.0)
    out["play_prob"] = pd.to_numeric(out.get("play_prob", 1.0), errors="coerce").fillna(1.0).clip(0, 1)
    out["proj_pts"] = pd.to_numeric(out.get("proj_pts", 0), errors="coerce").fillna(0.0)

    out["est_eo"] = (out["selected_by_percent"] * out["play_prob"]).round(1)
    cids = captain_ids or set()
    if cids and "id" in out.columns:
        out.loc[out["id"].astype(int).isin({int(x) for x in cids}), "est_eo"] = (
            out.loc[out["id"].astype(int).isin({int(x) for x in cids}), "est_eo"] * 2
        ).round(1)
    out["est_eo"] = out["est_eo"].clip(lower=0, upper=200)
    out["attack_index"] = (out["proj_pts"] * (1 - out["est_eo"] / 100.0)).round(2)
    return out


def compute_shield_attack_scores(
    players_with_eo: pd.DataFrame,
    *,
    squad_player_ids: set[int],
    top_n: int = 15,
    differential_eo_cap: float = 20.0,
) -> dict[str, Any]:
    """
    Compute shield/attack view from estimated EO.
    """
    if players_with_eo.empty or "id" not in players_with_eo.columns:
        return {
            "shield_score": 0.0,
            "attack_score": 0.0,
            "core_owned_count": 0,
            "core_total_count": int(top_n),
            "core_dangers": pd.DataFrame(),
            "attack_assets": pd.DataFrame(),
        }

    p = players_with_eo.copy()
    p["id"] = pd.to_numeric(p["id"], errors="coerce").fillna(-1).astype(int)
    p["est_eo"] = pd.to_numeric(p.get("est_eo", 0), errors="coerce").fillna(0.0)
    p["attack_index"] = pd.to_numeric(p.get("attack_index", 0), errors="coerce").fillna(0.0)
    p["proj_pts"] = pd.to_numeric(p.get("proj_pts", 0), errors="coerce").fillna(0.0)

    core = p.sort_values("est_eo", ascending=False).head(int(top_n)).copy()
    core["owned"] = core["id"].isin({int(x) for x in squad_player_ids})
    core_owned = core[core["owned"]]
    core_dangers = core[~core["owned"]].copy()

    shield_eo = float(core_owned["est_eo"].sum())
    danger_eo = float(core_dangers["est_eo"].sum())
    total_core = shield_eo + danger_eo
    shield_score = round((shield_eo / total_core) * 100, 1) if total_core > 0 else 0.0

    attack_assets = p[
        p["id"].isin({int(x) for x in squad_player_ids}) & (p["est_eo"] <= float(differential_eo_cap))
    ].copy()
    attack_assets = attack_assets.sort_values("attack_index", ascending=False)
    attack_max = float(attack_assets["proj_pts"].sum())
    attack_raw = float(attack_assets["attack_index"].sum())
    attack_score = round((attack_raw / attack_max) * 100, 1) if attack_max > 0 else 0.0

    return {
        "shield_score": shield_score,
        "attack_score": attack_score,
        "core_owned_count": int(core_owned.shape[0]),
        "core_total_count": int(core.shape[0]),
        "core_dangers": core_dangers.reset_index(drop=True),
        "attack_assets": attack_assets.reset_index(drop=True),
    }


def build_weekly_plan_markdown(
    *,
    gw_id: int | None,
    captain: dict[str, Any] | None,
    vice_captain: dict[str, Any] | None,
    xi_names: list[str],
    bench_names: list[str],
    transfer_note: str,
    chip_note: str,
    risk_notes: list[str] | None = None,
) -> str:
    """
    Render a concise markdown brief that can be downloaded/shared.
    """
    gw_label = f"GW{gw_id}" if gw_id else "Next GW"
    c_name = captain.get("web_name") if captain else "TBD"
    vc_name = vice_captain.get("web_name") if vice_captain else "TBD"
    c_opp = captain.get("Opp", "N/A") if captain else "N/A"
    vc_opp = vice_captain.get("Opp", "N/A") if vice_captain else "N/A"

    lines = [
        f"## {gw_label} Weekly Plan",
        "",
        f"- **Captain:** {c_name} (vs {c_opp})",
        f"- **Vice-captain:** {vc_name} (vs {vc_opp})",
        f"- **Suggested XI:** {', '.join(xi_names) if xi_names else 'N/A'}",
        f"- **Bench order:** {', '.join(bench_names) if bench_names else 'N/A'}",
        f"- **Transfer idea:** {transfer_note}",
        f"- **Chip strategy:** {chip_note}",
    ]
    risks = [r for r in (risk_notes or []) if str(r).strip()]
    lines.append("- **Key risks:**")
    if risks:
        lines.extend([f"  - {r}" for r in risks])
    else:
        lines.append("  - No major red flags detected.")
    return "\n".join(lines) + "\n"

