"""Descarga los archivos de hoopR (sportsdataverse) que usa la app NBA. Uso: python3 scripts/nba/download.py raw_nba"""
import sys, os, urllib.request, datetime
RAW = sys.argv[1] if len(sys.argv) > 1 else "raw_nba"
os.makedirs(RAW, exist_ok=True)
BASE = "https://raw.githubusercontent.com/sportsdataverse/hoopR-nba-data/main/nba/"
def get(path, name):
    try:
        urllib.request.urlretrieve(BASE + path, os.path.join(RAW, name)); print("ok", name); return True
    except Exception as e:
        print("no", name, e); return False
now = datetime.date.today().year + 1
years = [now, now - 1, now - 2]
pb = [y for y in years if get(f"player_box/parquet/player_box_{y}.parquet", f"player_box_{y}.parquet")]
for y in years:
    get(f"team_box/parquet/team_box_{y}.parquet", f"team_box_{y}.parquet")
    get(f"schedules/parquet/nba_schedule_{y}.parquet", f"nba_schedule_{y}.parquet")
for y in years:
    if get(f"rosters/parquet/rosters_{y}.parquet", f"rosters_{y}.parquet"):
        break
get("betting_lines/closing_lines_odds_api.parquet", "closing_lines_odds_api.parquet")
if not pb:
    sys.exit("No se pudo descargar ningún player_box")
