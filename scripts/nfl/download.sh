#!/usr/bin/env bash
# Descarga los datos de nflverse que usa la app NFL.
set -euo pipefail
RAW="${1:-raw_nfl}"; mkdir -p "$RAW"; cd "$RAW"
B=https://github.com/nflverse/nflverse-data/releases/download
get() { curl -sSLf --retry 3 -o "$(basename "$1")" "$1"; echo "ok $(basename "$1")"; }
for y in 2025 2026; do
  get $B/stats_player/stats_player_week_$y.csv
  get $B/weekly_rosters/roster_weekly_$y.csv
  get $B/pbp/play_by_play_$y.csv.gz
  get $B/snap_counts/snap_counts_$y.csv
done
get $B/stats_team/stats_team_week_2026.csv
get $B/injuries/injuries_2026.csv
get $B/teams/teams_colors_logos.csv
get https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv
