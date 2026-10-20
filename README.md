# Pizarra Props

Apps web de estadísticas para analizar props de la **NFL** y la **NBA** (en español, pensadas para celular).

- `nfl/` – datos de [nflverse](https://github.com/nflverse/nflverse-data)
- `nba/` – datos de [hoopR / sportsdataverse](https://github.com/sportsdataverse/hoopR-nba-data)

## Cómo se actualiza
El flujo `.github/workflows/actualizar.yml` corre todos los días a las 9:52 a. m. (hora del centro de México):
descarga los datos, regenera las páginas y las publica en GitHub Pages. También se puede correr a mano en
**Actions → Actualizar Pizarra Props → Run workflow**.

## Líneas de la NBA (moneyline, spread, total)
- Automático: crea una clave gratuita en [The Odds API](https://the-odds-api.com) y guárdala como secreto del
  repositorio con el nombre `ODDS_API_KEY` (**Settings → Secrets and variables → Actions → New repository secret**).
- Manual: edita `scripts/nba/lines_manual.json`.
Sin clave ni archivo manual, la app muestra "sin dato".
