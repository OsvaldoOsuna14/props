"""Líneas de los próximos partidos NBA desde The Odds API (opcional, necesita el secreto ODDS_API_KEY).
Escribe <raw>/lines_manual.json con el formato que lee process_nba.py. Sin clave, copia el archivo manual del repositorio.
Uso: python3 scripts/nba/fetch_odds.py raw_nba
"""
import sys, os, json, glob, shutil, urllib.request
import pandas as pd
RAW = sys.argv[1]
KEY = os.environ.get("ODDS_API_KEY", "").strip()
manual = os.path.join(os.path.dirname(__file__), "lines_manual.json")
out = os.path.join(RAW, "lines_manual.json")
if not KEY:
    if os.path.exists(manual):
        shutil.copy(manual, out)
    print("Sin ODDS_API_KEY: se usan las líneas manuales del repositorio (si hay)."); sys.exit(0)
url = ("https://api.the-odds-api.com/v4/sports/basketball_nba/odds?regions=us&markets=h2h,spreads,totals"
       f"&oddsFormat=american&bookmakers=draftkings,fanduel&apiKey={KEY}")
events = json.load(urllib.request.urlopen(url, timeout=30))
sched = pd.concat([pd.read_parquet(p) for p in sorted(glob.glob(f"{RAW}/nba_schedule_*.parquet"))[-1:]])
sched = sched[sched.status_type_completed == False].copy()
sched["dt"] = pd.to_datetime(sched.game_date_time, utc=True)
res = {}
for ev in events:
    t = pd.Timestamp(ev["commence_time"])
    m = sched[(sched.home_display_name == ev["home_team"]) & (sched.away_display_name == ev["away_team"]) & ((sched.dt - t).abs() < pd.Timedelta(hours=12))]
    if m.empty or not ev.get("bookmakers"):
        continue
    g = m.iloc[0]; bk = ev["bookmakers"][0]; mk = {x["key"]: x["outcomes"] for x in bk["markets"]}
    item = {"a": g.away_abbreviation, "h": g.home_abbreviation, "book": bk["title"], "asof": bk.get("last_update", "")[:10]}
    for o in mk.get("h2h", []):
        item["hml" if o["name"] == ev["home_team"] else "aml"] = o["price"]
    for o in mk.get("spreads", []):
        if o["name"] == ev["home_team"]:
            item["home_line"] = o["point"]
    for o in mk.get("totals", []):
        if o["name"] == "Over":
            item["total"] = o["point"]
    res[str(g.game_id)] = item
json.dump(res, open(out, "w"), ensure_ascii=False, indent=1)
print("líneas", len(res))
