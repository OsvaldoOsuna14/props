"""Convierte los datos de hoopR (sportsdataverse) en data.json para la app NBA.
Uso: python3 -I process_nba.py <carpeta_raw> <salida.json>
La carpeta debe tener player_box_YYYY.parquet, team_box_YYYY.parquet, nba_schedule_YYYY.parquet,
rosters_YYYY.parquet (el más reciente) y closing_lines_odds_api.parquet.
Temporada YYYY = la que termina en ese año (2026 = 2025-26).
"""
import sys, glob, json, math, re
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import pandas as pd

RAW, OUT = sys.argv[1], sys.argv[2]
MX = ZoneInfo("America/Mexico_City")
POS = {"G": "G", "PG": "G", "SG": "G", "F": "F", "SF": "F", "PF": "F", "C": "C", "FC": "F", "GF": "G"}
label = lambda y: f"{y-1}-{str(y)[2:]}"


def num(v, nd=None):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if nd is None:
        return int(round(v)) if abs(v - round(v)) < 1e-9 else round(v, 1)
    return round(v, nd)


def years(prefix):
    return sorted(int(re.search(r"(\d{4})", p).group(1)) for p in glob.glob(f"{RAW}/{prefix}_*.parquet"))


# ---------- temporadas ----------
pb_years = years("player_box")
loaded = {}
for y in pb_years:
    d = pd.read_parquet(f"{RAW}/player_box_{y}.parquet")
    d = d[(d.did_not_play == False) & d.minutes.notna()]
    if len(d):
        loaded[y] = d
CUR = max(loaded)
cur_reg_games = loaded[CUR][loaded[CUR].season_type == 2].game_id.nunique()
use_years = [CUR] + ([CUR - 1] if cur_reg_games < 300 and (CUR - 1) in loaded else [])
pb = pd.concat([loaded[y] for y in use_years])
pb["pos"] = pb.athlete_position_abbreviation.map(POS)

# ---------- equipos: nombres y colores ----------
sched = pd.concat([pd.read_parquet(f"{RAW}/nba_schedule_{y}.parquet") for y in years("nba_schedule")])
def lum(h):
    h = h.lstrip("#")
    if len(h) != 6:
        return 1
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
TEAMS = {}
for side in ("home", "away"):
    for _, r in sched.drop_duplicates(f"{side}_abbreviation", keep="last").iterrows():
        ab = r[f"{side}_abbreviation"]
        if not isinstance(ab, str) or ab in TEAMS or not r.get(f"{side}_is_active", True):
            continue
        c1 = "#" + str(r[f"{side}_color"] or "777777"); c2 = "#" + str(r[f"{side}_alternate_color"] or "ffffff")
        main = c2 if lum(c1) < 0.06 and lum(c2) > 0.06 else c1
        alt = c2 if main == c1 else c1
        if abs(lum(alt) - lum(main)) < 0.12:
            alt = "#ffffff" if lum(main) < 0.5 else "#111111"
        TEAMS[ab] = {"name": r[f"{side}_display_name"], "short": r[f"{side}_name"], "c": main, "c2": alt}
TEAMS = {k: v for k, v in TEAMS.items() if k in set(pb.team_abbreviation)}

# ---------- líneas de cierre ----------
bl = pd.read_parquet(f"{RAW}/closing_lines_odds_api.parquet")
bl["game_id"] = bl.game_id.astype(str)
LINES = {r.game_id: (r.home_point, r.over_under) for r in bl.itertuples()}

# ---------- partidos por jugador ----------
GCOLS = ["s", "d", "post", "tm", "op", "ha", "pf", "pa", "min", "pts", "reb", "oreb", "dreb", "ast", "stl", "blk", "tov",
         "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "pm", "st", "b2b", "lsp", "ltot"]
pb["gid"] = pb.game_id.astype(str)
pb["date"] = pd.to_datetime(pb.game_date).dt.date
# back-to-back: el equipo jugó el día anterior
tg = pb[["team_abbreviation", "date"]].drop_duplicates().sort_values(["team_abbreviation", "date"])
tg["prev"] = tg.groupby("team_abbreviation").date.shift()
b2b = {(r.team_abbreviation, r.date): 1 if r.prev is not None and r.prev == r.prev and (r.date - r.prev).days == 1 else 0 for r in tg.itertuples()}

ros = pd.read_parquet(sorted(glob.glob(f"{RAW}/rosters_*.parquet"))[-1])
ros["athlete_id"] = ros.athlete_id.astype(str).str.replace(r"\.0$", "", regex=True)
ros = ros.drop_duplicates("athlete_id", keep="last").set_index("athlete_id")
pb["aid"] = pb.athlete_id.astype("Int64").astype(str)

players = []
for aid, grp in pb.sort_values("game_date").groupby("aid"):
    if aid not in ros.index:
        continue  # solo jugadores con roster actual
    rr = ros.loc[aid]
    team = rr.team_abbreviation
    pos = POS.get(rr.position_abbreviation) or grp.pos.dropna().iloc[-1] if len(grp.pos.dropna()) else "F"
    rows = []
    for g in grp.itertuples():
        home = g.home_away == "home"
        hp, ou = LINES.get(g.gid, (None, None))
        lsp = None if hp is None or hp != hp else num(hp if home else -hp)
        rows.append([
            int(g.season), str(g.date), 0 if g.season_type == 2 else (2 if g.season_type == 3 else 1), g.team_abbreviation,
            g.opponent_team_abbreviation, "C" if home else "V", num(g.team_score), num(g.opponent_team_score),
            num(g.minutes), num(g.points), num(g.rebounds), num(g.offensive_rebounds), num(g.defensive_rebounds),
            num(g.assists), num(g.steals), num(g.blocks), num(g.turnovers), num(g.field_goals_made),
            num(g.field_goals_attempted), num(g.three_point_field_goals_made), num(g.three_point_field_goals_attempted),
            num(g.free_throws_made), num(g.free_throws_attempted), num(g.plus_minus), 1 if g.starter else 0,
            b2b.get((g.team_abbreviation, g.date), 0), lsp, num(ou) if ou is not None and ou == ou else None,
        ])
    jersey = num(rr.jersey) if str(rr.jersey).isdigit() else None
    players.append({"id": aid, "n": rr.display_name, "p": pos, "t": team, "j": jersey,
                    "rs": rr.status_name if isinstance(rr.status_name, str) else None, "inj": None, "g": rows})

# ---------- estadísticas de equipo ----------
TEAM_SEASON = CUR
tbs = {}
for y in years("team_box"):
    t = pd.read_parquet(f"{RAW}/team_box_{y}.parquet")
    tbs[y] = t[t.season_type == 2]
for y in tbs:
    tbs[y] = tbs[y][tbs[y].team_abbreviation.isin(TEAMS.keys()) & tbs[y].opponent_team_abbreviation.isin(TEAMS.keys())]
if tbs.get(CUR) is None or len(tbs[CUR]) == 0 or tbs[CUR].groupby("team_abbreviation").game_id.nunique().min() < 5:
    TEAM_SEASON = CUR - 1 if (CUR - 1) in tbs else CUR
tb = tbs[TEAM_SEASON].copy()
num_cols = ["team_score", "opponent_team_score", "field_goals_made", "field_goals_attempted", "three_point_field_goals_made",
            "three_point_field_goals_attempted", "free_throws_made", "free_throws_attempted", "total_rebounds",
            "offensive_rebounds", "defensive_rebounds", "assists", "steals", "blocks", "total_turnovers"]
for c in num_cols:
    tb[c] = pd.to_numeric(tb[c], errors="coerce")
own = tb.groupby("team_abbreviation")[num_cols].sum()
gp = tb.groupby("team_abbreviation").game_id.nunique()
opp = tb.groupby("opponent_team_abbreviation")[num_cols].sum()  # lo que hicieron los rivales contra cada equipo
def poss(r):
    return r.field_goals_attempted - r.offensive_rebounds + r.total_turnovers + 0.44 * r.free_throws_attempted
V = {}
for t in TEAMS:
    if t not in own.index:
        continue
    o, d, n = own.loc[t], opp.loc[t], gp[t]
    po, pd_ = poss(o), poss(d)
    V[t] = {
        "o_pts": o.team_score / n, "o_fgp": 100 * o.field_goals_made / o.field_goals_attempted,
        "o_3pm": o.three_point_field_goals_made / n, "o_3pp": 100 * o.three_point_field_goals_made / o.three_point_field_goals_attempted,
        "o_ftp": 100 * o.free_throws_made / o.free_throws_attempted, "o_reb": o.total_rebounds / n,
        "o_oreb": o.offensive_rebounds / n, "o_ast": o.assists / n, "o_tov": o.total_turnovers / n,
        "o_pace": (po + pd_) / 2 / n, "o_rtg": 100 * o.team_score / po,
        "d_pts": d.team_score / n, "d_fgp": 100 * d.field_goals_made / d.field_goals_attempted,
        "d_3pm": d.three_point_field_goals_made / n, "d_3pp": 100 * d.three_point_field_goals_made / d.three_point_field_goals_attempted,
        "d_reb": d.total_rebounds / n, "d_ast": d.assists / n, "d_stl": o.steals / n, "d_blk": o.blocks / n,
        "d_tovf": d.total_turnovers / n, "d_rtg": 100 * d.team_score / pd_,
    }
# permitido por posición (jugadores rivales, temporada regular de la temporada de equipos)
pbt = loaded.get(TEAM_SEASON)
if pbt is not None:
    pbt = pbt[pbt.season_type == 2].copy()
    pbt["pos"] = pbt.athlete_position_abbreviation.map(POS)
    for c in ("points", "rebounds", "assists", "three_point_field_goals_made"):
        pbt[c] = pd.to_numeric(pbt[c], errors="coerce")
    bp = pbt.groupby(["opponent_team_abbreviation", "pos"])[["points", "rebounds", "assists", "three_point_field_goals_made"]].sum()
    for t in V:
        n = gp[t]
        for p in ("G", "F", "C"):
            r = bp.loc[(t, p)] if (t, p) in bp.index else None
            pk = p.lower()
            V[t][f"{pk}_pts"] = (r.points / n) if r is not None else None
            V[t][f"{pk}_reb"] = (r.rebounds / n) if r is not None else None
            V[t][f"{pk}_ast"] = (r.assists / n) if r is not None else None
            V[t][f"{pk}_3pm"] = (r.three_point_field_goals_made / n) if r is not None else None

COLS = [
    ("o_pts", "Puntos", "Ofensiva", 1, True), ("o_rtg", "Puntos por 100 posesiones", "Ofensiva", 1, True),
    ("o_pace", "Ritmo (posesiones)", "Ofensiva", 1, True), ("o_fgp", "% de campo", "Ofensiva", 1, True),
    ("o_3pm", "Triples anotados", "Ofensiva", 1, True), ("o_3pp", "% de triples", "Ofensiva", 1, True),
    ("o_ftp", "% de tiros libres", "Ofensiva", 1, True), ("o_reb", "Rebotes", "Ofensiva", 1, True),
    ("o_oreb", "Rebotes ofensivos", "Ofensiva", 1, True), ("o_ast", "Asistencias", "Ofensiva", 1, True),
    ("o_tov", "Pérdidas", "Ofensiva", 1, False),
    ("d_pts", "Puntos permitidos", "Defensiva", 1, False), ("d_rtg", "Puntos permitidos por 100 posesiones", "Defensiva", 1, False),
    ("d_fgp", "% de campo permitido", "Defensiva", 1, False), ("d_3pm", "Triples permitidos", "Defensiva", 1, False),
    ("d_3pp", "% de triples permitido", "Defensiva", 1, False), ("d_reb", "Rebotes permitidos", "Defensiva", 1, False),
    ("d_ast", "Asistencias permitidas", "Defensiva", 1, False), ("d_stl", "Robos", "Defensiva", 1, True),
    ("d_blk", "Bloqueos", "Defensiva", 1, True), ("d_tovf", "Pérdidas forzadas", "Defensiva", 1, True),
]
for p, pn in (("g", "bases y escoltas (G)"), ("f", "aleros y alas-pívot (F)"), ("c", "pívots (C)")):
    COLS += [(f"{p}_pts", f"Puntos permitidos a {pn}", "Vs posición", 1, False),
             (f"{p}_reb", f"Rebotes permitidos a {pn}", "Vs posición", 1, False),
             (f"{p}_ast", f"Asistencias permitidas a {pn}", "Vs posición", 1, False),
             (f"{p}_3pm", f"Triples permitidos a {pn}", "Vs posición", 1, False)]

teams_out = {t: {"name": TEAMS[t]["name"], "short": TEAMS[t]["short"], "c": TEAMS[t]["c"], "c2": TEAMS[t]["c2"],
                 "gp": int(gp.get(t, 0)), "v": {}, "r": {}} for t in TEAMS}
for key, _, _, nd, hib in COLS:
    vals = pd.Series({t: (V.get(t) or {}).get(key) for t in TEAMS}, dtype="float")
    ranks = vals.rank(ascending=not hib, method="min")
    for t in TEAMS:
        v = vals[t]
        teams_out[t]["v"][key] = None if pd.isna(v) else round(float(v), nd)
        teams_out[t]["r"][key] = None if pd.isna(ranks[t]) else int(ranks[t])

# ---------- récords como favorito / underdog e historial con línea ----------
def team_games(y):
    t = tbs.get(y)
    if t is None:
        return []
    t = t[t.team_home_away == "home"].copy()
    t["gid"] = t.game_id.astype(str)
    return t.sort_values("game_date")
league_rec, total_vals = {}, []
for y in sorted(tbs):
    hg = team_games(y)
    if len(hg) == 0:
        continue
    rec = {t: dict(fw=0, fl=0, ft=0, dw=0, dl=0, dt=0, pkw=0, pkl=0, pkt=0, afw=0, afl=0, afp=0, adw=0, adl=0, adp=0, ov=0, un=0, op=0) for t in TEAMS}
    gl = {t: [] for t in TEAMS}
    lg = dict(fw=0, fl=0, ft=0, afw=0, afl=0, afp=0, ov=0, un=0, op=0, n=0)
    for g in hg.itertuples():
        h, a = g.team_abbreviation, g.opponent_team_abbreviation
        hs, as_ = float(g.team_score), float(g.opponent_team_score)
        hp, ou = LINES.get(g.gid, (None, None))
        hp = None if hp is None or hp != hp else float(hp)
        ou = None if ou is None or ou != ou else float(ou)
        if ou is not None:
            total_vals.append(ou)
        for team, home in ((h, True), (a, False)):
            if team not in rec:
                continue
            line = None if hp is None else (hp if home else -hp)
            pf, pa = (hs, as_) if home else (as_, hs)
            gl[team].append([str(g.game_date)[:10], a if home else h, "C" if home else "V", num(line), num(pf), num(pa), num(ou)])
            if line is None:
                continue
            R = rec[team]; m = pf - pa
            out = "w" if m > 0 else "l" if m < 0 else "t"
            c = m + line; ats = "w" if c > 0 else "l" if c < 0 else "p"
            if line < 0:
                R["f" + out] += 1; R["af" + ats] += 1
            elif line > 0:
                R["d" + out] += 1; R["ad" + ats] += 1
            else:
                R["pk" + out] += 1
            if ou is not None:
                R["ov" if pf + pa > ou else "un" if pf + pa < ou else "op"] += 1
        if hp is not None and hp != 0:
            fm = (hs - as_) if hp < 0 else (as_ - hs)
            lg["fw" if fm > 0 else "fl" if fm < 0 else "ft"] += 1
            c = fm - abs(hp)
            lg["afw" if c > 0 else "afl" if c < 0 else "afp"] += 1
            lg["n"] += 1
        if ou is not None:
            tot = hs + as_
            lg["ov" if tot > ou else "un" if tot < ou else "op"] += 1
    if lg["n"]:
        league_rec[str(y)] = lg
        for t in teams_out:
            teams_out[t].setdefault("rec", {})[str(y)] = rec[t]
            teams_out[t].setdefault("gl", {})[str(y)] = gl[t]
total_median = float(pd.Series(total_vals).median()) if total_vals else None

# ---------- próximos partidos ----------
now = datetime.now(timezone.utc)
up = sched[(sched.status_type_completed == False)].copy()
up["dt"] = pd.to_datetime(up.game_date_time, utc=True)
up = up[(up.dt >= now - timedelta(hours=6)) & (up.dt <= now + timedelta(days=14))].sort_values("dt")
# líneas de partidos próximos buscadas en internet (opcional): {game_id: {a, h, home_line, total, aml, hml, book, asof}}
MANUAL = {}
try:
    with open(f"{RAW}/lines_manual.json") as f:
        MANUAL = {str(k): v for k, v in json.load(f).items()}
except FileNotFoundError:
    pass
upcoming = []
for g in up.itertuples():
    if g.home_abbreviation not in TEAMS or g.away_abbreviation not in TEAMS:
        continue
    hp, ou = LINES.get(str(g.game_id), (None, None))
    item = {"id": str(g.game_id), "mx": g.dt.tz_convert(MX).strftime("%Y-%m-%dT%H:%M"), "a": g.away_abbreviation,
            "h": g.home_abbreviation, "sp": None if hp is None or hp != hp else num(-hp), "tot": num(ou),
            "st": g.venue_full_name if isinstance(g.venue_full_name, str) else None, "neu": 1 if g.neutral_site else 0}
    m = MANUAL.get(str(g.game_id))
    if m and m.get("h") == g.home_abbreviation and m.get("a") == g.away_abbreviation:
        if m.get("home_line") is not None: item["sp"] = num(-float(m["home_line"]))   # positivo = local favorito
        if m.get("total") is not None: item["tot"] = num(m["total"])
        if m.get("aml") is not None: item["aml"] = num(m["aml"])
        if m.get("hml") is not None: item["hml"] = num(m["hml"])
        item["src"] = f"{m.get('book', 'casa')} · {m.get('asof', '')}".strip(" ·")
    upcoming.append(item)

last_date = str(max(pd.to_datetime(loaded[CUR].game_date)).date())
out = {
    "meta": {"generated": now.isoformat(timespec="minutes"), "season": CUR, "seasonLabel": label(CUR),
             "seasons": use_years, "teamSeason": TEAM_SEASON, "teamSeasonLabel": label(TEAM_SEASON),
             "lastDate": last_date, "source": "hoopR / sportsdataverse (hoopR-nba-data)", "gcols": GCOLS},
    "cols": [{"k": k, "l": l, "g": g, "d": d, "hib": h} for k, l, g, d, h in COLS],
    "teams": teams_out, "players": players, "upcoming": upcoming,
    "league": {"rec": league_rec, "totalMedian": total_median},
}
with open(OUT, "w") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print("jugadores", len(players), "temporada", label(CUR), "equipos", label(TEAM_SEASON), "proximos", len(upcoming),
      "KB", round(len(json.dumps(out, separators=(",", ":"))) / 1024))
