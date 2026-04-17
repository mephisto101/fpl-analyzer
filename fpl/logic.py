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

