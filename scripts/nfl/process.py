"""Convierte los CSV de nflverse en un solo data.json compacto para la app.
Uso: python3 -I process.py <carpeta_raw> <salida.json>
"""
import sys, json, math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pandas as pd

RAW, OUT = sys.argv[1], sys.argv[2]
SEASON, PREV = 2026, 2025
POS_MAP = {"QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE"}

TEAM_NAMES = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens", "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers", "CHI": "Chicago Bears", "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys", "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars", "KC": "Kansas City Chiefs",
    "LA": "Los Angeles Rams", "LAC": "Los Angeles Chargers", "LV": "Las Vegas Raiders", "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings", "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants",
    "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers", "SEA": "Seattle Seahawks",
    "SF": "San Francisco 49ers", "TB": "Tampa Bay Buccaneers", "TEN": "Tennessee Titans", "WAS": "Washington Commanders",
}


def num(v, nd=None):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    v = float(v)
    if nd is None:
        return int(round(v)) if abs(v - round(v)) < 1e-9 else v
    return round(v, nd)


# ---------- calendario ----------
games = pd.read_csv(f"{RAW}/games.csv")
games = games[games.season.isin([PREV, SEASON])]
gidx = games.set_index("game_id")

# ---------- jugada por jugada: recepción y carrera más larga ----------
def longest(pbp):
    rec = pbp[(pbp.complete_pass == 1) & pbp.receiver_player_id.notna() & (pbp.two_point_attempt != 1)]
    lr = rec.groupby(["game_id", "receiver_player_id"]).receiving_yards.max()
    ru = pbp[(pbp.play_type == "run") & pbp.rusher_player_id.notna() & (pbp.two_point_attempt != 1)]
    lu = ru.groupby(["game_id", "rusher_player_id"]).rushing_yards.max()
    return lr.to_dict(), lu.to_dict()

PBP_COLS = ["game_id", "play_type", "posteam", "defteam", "down", "third_down_converted", "third_down_failed",
            "fixed_drive", "fixed_drive_result", "drive_inside20", "complete_pass", "receiver_player_id",
            "receiving_yards", "rusher_player_id", "rushing_yards", "two_point_attempt", "season_type", "week", "yardline_100"]
pbp_cur = pd.read_csv(f"{RAW}/play_by_play_{SEASON}.csv.gz", usecols=PBP_COLS, low_memory=False)
pbp_prev = pd.read_csv(f"{RAW}/play_by_play_{PREV}.csv.gz", usecols=PBP_COLS, low_memory=False)
long_rec, long_rush = {}, {}
for p in (pbp_prev, pbp_cur):
    a, b = longest(p)
    long_rec.update(a); long_rush.update(b)

# uso en zona roja (dentro de la 20): acarreos y targets por partido
rz_car, rz_tgt = {}, {}
for p in (pbp_prev, pbp_cur):
    z = p[(p.yardline_100 <= 20) & (p.two_point_attempt != 1)]
    rz_car.update(z[(z.play_type == "run") & z.rusher_player_id.notna()].groupby(["game_id", "rusher_player_id"]).size().to_dict())
    rz_tgt.update(z[(z.play_type == "pass") & z.receiver_player_id.notna()].groupby(["game_id", "receiver_player_id"]).size().to_dict())

# snaps ofensivos (pfr_id -> gsis_id con los rosters de ambas temporadas)
idmap = {}
for y in (PREV, SEASON):
    rr = pd.read_csv(f"{RAW}/roster_weekly_{y}.csv", usecols=["gsis_id", "pfr_id"], low_memory=False).dropna()
    idmap.update(dict(zip(rr.pfr_id, rr.gsis_id)))
snaps = {}
for y in (PREV, SEASON):
    sc = pd.read_csv(f"{RAW}/snap_counts_{y}.csv")
    for gid, pfr, pct in zip(sc.game_id, sc.pfr_player_id, sc.offense_pct):
        gs = idmap.get(pfr)
        if gs is not None and pct == pct:
            snaps[(gid, gs)] = round(100 * float(pct))

# ---------- estadísticas de jugador ----------
ps = pd.concat([
    pd.read_csv(f"{RAW}/stats_player_week_{PREV}.csv", low_memory=False),
    pd.read_csv(f"{RAW}/stats_player_week_{SEASON}.csv", low_memory=False),
])
ps = ps[ps.season_type.isin(["REG", "POST"])]
ps = ps.copy(); ps["pos"] = ps.position.map(POS_MAP)
cur = ps[ps.season == SEASON]
last_week = int(cur.week.max())

# jugadores relevantes: posición ofensiva en 2026 o en roster actual
ros = pd.read_csv(f"{RAW}/roster_weekly_{SEASON}.csv", low_memory=False)
ros_last = ros[ros.week == ros.week.max()].drop_duplicates("gsis_id", keep="last").set_index("gsis_id")
inj = pd.read_csv(f"{RAW}/injuries_{SEASON}.csv")
inj_week = int(inj.week.max())
inj_last = inj[inj.week == inj_week].drop_duplicates("gsis_id", keep="last").set_index("gsis_id")

ROSTER_STATUS = {"ACT": "Activo", "INA": "Inactivo", "DEV": "Practice squad", "CUT": "Liberado",
                 "RET": "Retirado", "EXE": "Exento"}
RES_STATUS = {"R01": "Lista de lesionados (IR)", "R48": "IR – designado para regresar", "R04": "PUP",
              "R05": "NFI", "R40": "Suspendido", "R49": "Suspendido"}
INJ_ES = {"Out": "Fuera", "Doubtful": "Dudoso", "Questionable": "En duda"}

def roster_status(pid):
    if pid not in ros_last.index:
        return None
    r = ros_last.loc[pid]
    if r.status == "RES":
        return RES_STATUS.get(r.status_description_abbr, "Reserva")
    return ROSTER_STATUS.get(r.status, r.status)

# columnas por partido (orden fijo; la app lo lee de meta.gcols)
GCOLS = ["s", "w", "post", "tm", "op", "ha", "pf", "pa",
         "cmp", "att", "pyd", "ptd", "int", "car", "ryd", "rtd", "lru", "tgt", "rec", "recyd", "rectd", "lrec",
         "snp", "tsh", "ash", "rzc", "rzt", "roof", "tmp", "wnd", "lsp", "ltot"]
ROOF = {"outdoors": "aire", "dome": "domo", "closed": "cerrado", "open": "abierto"}

players = []
off = ps[ps.pos.notna()]
for pid, grp in off.groupby("player_id"):
    grp = grp.sort_values(["season", "week"])
    lastrow = grp.iloc[-1]
    in_ros = pid in ros_last.index
    if not in_ros and lastrow.season != SEASON:
        continue  # no está en un roster actual ni jugó en 2026
    pos = POS_MAP.get(ros_last.loc[pid].position, lastrow.pos) if in_ros else lastrow.pos
    team = ros_last.loc[pid].team if in_ros else lastrow.team
    rows = []
    for _, g in grp.iterrows():
        gi = gidx.loc[g.game_id] if g.game_id in gidx.index else None
        if gi is not None:
            if gi.location == "Neutral":
                ha = "N"
            else:
                ha = "C" if g.team == gi.home_team else "V"
            home = g.team == gi.home_team
            pf = num(gi.home_score if home else gi.away_score)
            pa = num(gi.away_score if home else gi.home_score)
        else:
            ha, pf, pa = None, None, None
        roof = ROOF.get(gi.roof) if gi is not None and isinstance(gi.roof, str) else None
        tmp = num(gi.temp) if gi is not None else None
        wnd = num(gi.wind) if gi is not None else None
        # línea del partido desde el punto de vista del equipo del jugador (negativo = favorito)
        lsp = ltot = None
        if gi is not None and gi.spread_line == gi.spread_line:
            lsp = num(-gi.spread_line if g.team == gi.home_team else gi.spread_line)
        if gi is not None and gi.total_line == gi.total_line:
            ltot = num(gi.total_line)
        tsh = None if pd.isna(g.target_share) else round(100 * float(g.target_share))
        ash = None if pd.isna(g.air_yards_share) else round(100 * float(g.air_yards_share))
        recs = num(g.receptions)
        lrec = long_rec.get((g.game_id, pid))
        if lrec is None and recs == 0:
            lrec = 0
        car = num(g.carries)
        lru = long_rush.get((g.game_id, pid))
        if lru is None and car == 0:
            lru = 0
        rows.append([
            int(g.season), int(g.week), 1 if g.season_type == "POST" else 0, g.team, g.opponent_team, ha, pf, pa,
            num(g.completions), num(g.attempts), num(g.passing_yards), num(g.passing_tds), num(g.passing_interceptions),
            car, num(g.rushing_yards), num(g.rushing_tds), num(lru), num(g.targets), recs,
            num(g.receiving_yards), num(g.receiving_tds), num(lrec),
            snaps.get((g.game_id, pid)), tsh, ash,
            rz_car.get((g.game_id, pid), 0), rz_tgt.get((g.game_id, pid), 0), roof, tmp, wnd, lsp, ltot,
        ])
    injury = None
    if pid in inj_last.index:
        r = inj_last.loc[pid]
        if isinstance(r.report_status, str):
            body = r.report_primary_injury if isinstance(r.report_primary_injury, str) else None
            injury = {"st": INJ_ES.get(r.report_status, r.report_status), "en": r.report_status, "body": body,
                      "wk": inj_week}
    jersey = None
    if in_ros:
        jv = ros_last.loc[pid].jersey_number
        jersey = int(jv) if jv == jv else None
    players.append({"id": pid, "n": lastrow.player_display_name, "p": pos, "t": team, "j": jersey,
                    "rs": roster_status(pid), "inj": injury, "g": rows})

# ---------- estadísticas de equipo ----------
ts = pd.read_csv(f"{RAW}/stats_team_week_{SEASON}.csv")
ts = ts[ts.season_type == "REG"]
gcur = games[(games.season == SEASON) & (games.game_type == "REG") & games.home_score.notna()]

T = {t: {} for t in TEAM_NAMES}
gp = ts.groupby("team").game_id.nunique()
for t in T:
    T[t]["gp"] = int(gp.get(t, 0))

# puntos
pts_for, pts_ag = {t: 0 for t in T}, {t: 0 for t in T}
for _, g in gcur.iterrows():
    pts_for[g.home_team] += g.home_score; pts_ag[g.home_team] += g.away_score
    pts_for[g.away_team] += g.away_score; pts_ag[g.away_team] += g.home_score

sums = ts.groupby("team").sum(numeric_only=True)
opp = ts.groupby("opponent_team").sum(numeric_only=True)  # lo que hicieron los rivales contra cada equipo

def side(s, t):
    r = s.loc[t]
    net_pass = r.passing_yards - r.sack_yards_lost
    return {
        "yds": net_pass + r.rushing_yards, "pyd": net_pass, "ryd": r.rushing_yards,
        "ypc": r.rushing_yards / r.carries if r.carries else None,
        "ypa": r.passing_yards / r.attempts if r.attempts else None,
        "ptd": r.passing_tds, "rtd": r.rushing_tds, "sk": r.sacks_suffered,
        "to": r.passing_interceptions + r.fumbles_lost_total,
    }

# tercera oportunidad y zona roja (pbp 2026, temporada regular)
pb = pbp_cur[pbp_cur.season_type == "REG"]
td3 = pb[(pb.third_down_converted == 1) | (pb.third_down_failed == 1)]
o3 = td3.groupby("posteam").agg(c=("third_down_converted", "sum"), n=("game_id", "size"))
d3 = td3.groupby("defteam").agg(c=("third_down_converted", "sum"), n=("game_id", "size"))
drv = pb[pb.fixed_drive.notna() & pb.posteam.notna()].groupby(["game_id", "posteam", "fixed_drive"]).agg(
    defteam=("defteam", "first"), rz=("drive_inside20", "max"), res=("fixed_drive_result", "first")).reset_index()
rz = drv[drv.rz == 1].copy()
rz["td"] = (rz.res == "Touchdown").astype(int)
orz = rz.groupby("posteam").agg(td=("td", "sum"), n=("td", "size"))
drz = rz.groupby("defteam").agg(td=("td", "sum"), n=("td", "size"))

# por posición permitido
cp = cur[cur.season_type == "REG"]
by_pos = cp.groupby(["opponent_team", "pos"]).sum(numeric_only=True)

def pos_allowed(t, pos):
    if (t, pos) not in by_pos.index:
        return dict(pyd=0, ptd=0, ryd=0, rtd=0, rec=0, recyd=0, rectd=0)
    r = by_pos.loc[(t, pos)]
    return dict(pyd=r.passing_yards, ptd=r.passing_tds, ryd=r.rushing_yards, rtd=r.rushing_tds,
                rec=r.receptions, recyd=r.receiving_yards, rectd=r.receiving_tds)

for t in T:
    n = T[t]["gp"]
    if n == 0:
        continue
    o, d = side(sums, t), side(opp, t)
    pg = lambda v: v / n
    T[t].update({
        "o_pts": pg(pts_for[t]), "o_yds": pg(o["yds"]), "o_pyd": pg(o["pyd"]), "o_ryd": pg(o["ryd"]),
        "o_ypc": o["ypc"], "o_ypa": o["ypa"], "o_ptd": pg(o["ptd"]), "o_rtd": pg(o["rtd"]),
        "o_3d": 100 * o3.loc[t].c / o3.loc[t].n if t in o3.index else None,
        "o_rz": 100 * orz.loc[t].td / orz.loc[t].n if t in orz.index else None,
        "o_sk": pg(o["sk"]), "o_to": pg(o["to"]),
        "d_pts": pg(pts_ag[t]), "d_yds": pg(d["yds"]), "d_pyd": pg(d["pyd"]), "d_ryd": pg(d["ryd"]),
        "d_ypc": d["ypc"], "d_ptd": pg(d["ptd"]), "d_rtd": pg(d["rtd"]),
        "d_sk": pg(sums.loc[t].def_sacks), "d_int": pg(sums.loc[t].def_interceptions),
        "d_3d": 100 * d3.loc[t].c / d3.loc[t].n if t in d3.index else None,
        "d_rz": 100 * drz.loc[t].td / drz.loc[t].n if t in drz.index else None,
    })
    qb, rb, wr, te = (pos_allowed(t, p) for p in ("QB", "RB", "WR", "TE"))
    T[t].update({
        "qb_yd": pg(qb["pyd"]), "qb_td": pg(qb["ptd"]),
        "rb_ryd": pg(rb["ryd"]), "rb_recyd": pg(rb["recyd"]), "rb_td": pg(rb["rtd"] + rb["rectd"]),
        "wr_rec": pg(wr["rec"]), "wr_yd": pg(wr["recyd"]), "wr_td": pg(wr["rectd"]),
        "te_rec": pg(te["rec"]), "te_yd": pg(te["recyd"]), "te_td": pg(te["rectd"]),
    })

# columnas: clave, etiqueta, grupo, decimales, mayor_es_mejor
COLS = [
    ("o_pts", "Puntos", "Ofensiva", 1, True), ("o_yds", "Yardas totales", "Ofensiva", 1, True),
    ("o_pyd", "Yardas de pase (netas)", "Ofensiva", 1, True), ("o_ryd", "Yardas por tierra", "Ofensiva", 1, True),
    ("o_ypc", "Yardas por acarreo", "Ofensiva", 2, True), ("o_ypa", "Yardas por intento de pase", "Ofensiva", 2, True),
    ("o_ptd", "TDs de pase", "Ofensiva", 2, True), ("o_rtd", "TDs por tierra", "Ofensiva", 2, True),
    ("o_3d", "% 3ª oportunidad", "Ofensiva", 1, True), ("o_rz", "% TD zona roja", "Ofensiva", 1, True),
    ("o_sk", "Capturas permitidas", "Ofensiva", 2, False), ("o_to", "Balones perdidos", "Ofensiva", 2, False),
    ("d_pts", "Puntos permitidos", "Defensiva", 1, False), ("d_yds", "Yardas totales permitidas", "Defensiva", 1, False),
    ("d_pyd", "Yardas de pase permitidas", "Defensiva", 1, False), ("d_ryd", "Yardas por tierra permitidas", "Defensiva", 1, False),
    ("d_ypc", "Yardas por acarreo permitidas", "Defensiva", 2, False), ("d_ptd", "TDs de pase permitidos", "Defensiva", 2, False),
    ("d_rtd", "TDs por tierra permitidos", "Defensiva", 2, False), ("d_sk", "Capturas", "Defensiva", 2, True),
    ("d_int", "Intercepciones", "Defensiva", 2, True), ("d_3d", "% 3ª oportunidad permitido", "Defensiva", 1, False),
    ("d_rz", "% TD zona roja permitido", "Defensiva", 1, False),
    ("qb_yd", "Yardas de pase de QB permitidas", "Vs posición", 1, False), ("qb_td", "TDs de pase de QB permitidos", "Vs posición", 2, False),
    ("rb_ryd", "Yardas por tierra de RB permitidas", "Vs posición", 1, False), ("rb_recyd", "Yardas por recepción de RB permitidas", "Vs posición", 1, False),
    ("rb_td", "TDs de RB permitidos", "Vs posición", 2, False),
    ("wr_rec", "Recepciones de WR permitidas", "Vs posición", 1, False), ("wr_yd", "Yardas de WR permitidas", "Vs posición", 1, False),
    ("wr_td", "TDs de WR permitidos", "Vs posición", 2, False),
    ("te_rec", "Recepciones de TE permitidas", "Vs posición", 1, False), ("te_yd", "Yardas de TE permitidas", "Vs posición", 1, False),
    ("te_td", "TDs de TE permitidos", "Vs posición", 2, False),
]
# colores del equipo (si el primario es casi negro, se usa el secundario para que se vea sobre fondo oscuro)
def lum(h):
    h = h.lstrip("#"); r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
COLORS, COLORS2 = {}, {}
try:
    tc = pd.read_csv(f"{RAW}/teams_colors_logos.csv")
    for _, r in tc.iterrows():
        c1, c2 = str(r.team_color), str(r.team_color2)
        COLORS[r.team_abbr] = c2 if lum(c1) < 0.09 and c2.startswith("#") else c1
        alt = c2 if COLORS[r.team_abbr] == c1 else c1
        if lum(alt) < 0.12 or alt.lower() == COLORS[r.team_abbr].lower():
            alt = "#ffffff"
        COLORS2[r.team_abbr] = alt
except FileNotFoundError:
    pass
teams_out = {}
for t in T:
    teams_out[t] = {"name": TEAM_NAMES[t], "gp": T[t]["gp"], "c": COLORS.get(t, "#8899bb"), "c2": COLORS2.get(t, "#ffffff"), "v": {}, "r": {}}
for key, _, _, nd, hib in COLS:
    vals = pd.Series({t: T[t].get(key) for t in T}, dtype="float")
    ranks = vals.rank(ascending=not hib, method="min")
    for t in T:
        v = vals[t]
        teams_out[t]["v"][key] = None if pd.isna(v) else round(float(v), nd)
        teams_out[t]["r"][key] = None if pd.isna(ranks[t]) else int(ranks[t])

# ---------- récords como favorito / underdog (temporada regular, línea del calendario) ----------
def records(season):
    gs = games[(games.season == season) & (games.game_type == "REG") & games.home_score.notna() & games.spread_line.notna()]
    rec = {t: dict(fw=0, fl=0, ft=0, dw=0, dl=0, dt=0, pkw=0, pkl=0, pkt=0, afw=0, afl=0, afp=0, adw=0, adl=0, adp=0, ov=0, un=0, op=0) for t in TEAM_NAMES}
    lg = dict(fw=0, fl=0, ft=0, afw=0, afl=0, afp=0, ov=0, un=0, op=0, n=0)
    for _, g in gs.iterrows():
        res = g.home_score - g.away_score
        for team, is_home in ((g.home_team, True), (g.away_team, False)):
            if team not in rec:
                continue
            R = rec[team]
            line = -g.spread_line if is_home else g.spread_line   # negativo = favorito
            margin = res if is_home else -res
            out = "w" if margin > 0 else "l" if margin < 0 else "t"
            cover = margin + line                                  # >0 cubre
            ats = "w" if cover > 0 else "l" if cover < 0 else "p"
            if line < 0:
                R["f" + out] += 1; R["af" + ats] += 1
            elif line > 0:
                R["d" + out] += 1; R["ad" + ats] += 1
            else:
                R["pk" + out] += 1
            if g.total_line == g.total_line:
                tot = g.home_score + g.away_score
                R["ov" if tot > g.total_line else "un" if tot < g.total_line else "op"] += 1
        # liga: desde el favorito
        if g.spread_line != 0:
            fav_home = g.spread_line > 0
            fm = res if fav_home else -res
            lg["fw" if fm > 0 else "fl" if fm < 0 else "ft"] += 1
            c = fm - abs(g.spread_line)
            lg["afw" if c > 0 else "afl" if c < 0 else "afp"] += 1
            lg["n"] += 1
        if g.total_line == g.total_line:
            tot = g.home_score + g.away_score
            lg["ov" if tot > g.total_line else "un" if tot < g.total_line else "op"] += 1
    return rec, lg
REC = {}
for y in (PREV, SEASON):
    REC[y] = records(y)
for t in teams_out:
    teams_out[t]["rec"] = {str(y): REC[y][0][t] for y in REC}
# partidos de cada equipo con su línea, para ver el detalle de cada récord: [sem, rival, C/V/N, línea propia, pf, pa, total línea]
for y in (PREV, SEASON):
    gs = games[(games.season == y) & (games.game_type == "REG") & games.home_score.notna()].sort_values("week")
    for t in teams_out:
        teams_out[t].setdefault("gl", {})[str(y)] = []
    for _, g in gs.iterrows():
        for team, home in ((g.home_team, True), (g.away_team, False)):
            if team not in teams_out:
                continue
            line = None if g.spread_line != g.spread_line else num(-g.spread_line if home else g.spread_line)
            teams_out[team]["gl"][str(y)].append([int(g.week), g.away_team if home else g.home_team,
                "N" if g.location == "Neutral" else ("C" if home else "V"), line,
                num(g.home_score if home else g.away_score), num(g.away_score if home else g.home_score),
                num(g.total_line)])
league_rec = {str(y): REC[y][1] for y in REC}
tl = games[games.total_line.notna() & games.season.isin([PREV, SEASON])].total_line
total_median = float(tl.median()) if len(tl) else None

# ---------- próximos partidos (para fases siguientes) ----------
MX = ZoneInfo("America/Mexico_City"); ET = ZoneInfo("America/New_York")
up = games[(games.season == SEASON) & games.home_score.isna()].sort_values(["gameday", "gametime"])
upcoming = []
for _, g in up.iterrows():
    dt = datetime.fromisoformat(f"{g.gameday}T{g.gametime}").replace(tzinfo=ET).astimezone(MX)
    upcoming.append({"id": g.game_id, "wk": int(g.week), "mx": dt.strftime("%Y-%m-%dT%H:%M"), "a": g.away_team,
                     "h": g.home_team, "sp": num(g.spread_line), "tot": num(g.total_line),
                     "aml": num(g.away_moneyline), "hml": num(g.home_moneyline),
                     "roof": ROOF.get(g.roof) if isinstance(g.roof, str) else None,
                     "st": g.stadium if isinstance(g.stadium, str) else None,
                     "neu": 1 if g.location == "Neutral" else 0, "div": int(g.div_game) if g.div_game == g.div_game else 0})

out = {
    "meta": {
        "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "season": SEASON, "lastWeek": last_week, "injWeek": inj_week,
        "gamesThrough": sorted(cur[cur.week == last_week].game_id.unique().tolist()),
        "source": "nflverse (github.com/nflverse/nflverse-data, nfldata games.csv)",
        "gcols": GCOLS,
    },
    "cols": [{"k": k, "l": l, "g": g, "d": d, "hib": h} for k, l, g, d, h in COLS],
    "teams": teams_out,
    "players": players,
    "upcoming": upcoming,
    "league": {"rec": league_rec, "totalMedian": total_median},
}
with open(OUT, "w") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print("jugadores", len(players), "semana", last_week, "lesiones sem", inj_week, "KB", round(len(json.dumps(out)) / 1024))
