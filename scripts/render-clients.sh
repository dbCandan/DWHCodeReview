#!/usr/bin/env sh
set -eu

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
mode="write"
usage="usage: scripts/render-clients.sh [--check [--ci]|--validate]"
case "${1:-}" in
  --check)
    # --ci: projenin CI'ı; projeye kaydedilmiş yönetişimi atlatan asistan ayarı her cihazda durur.
    case "$#:${2:-}" in
      1:) exec python3 "$root/scripts/check-governance-drift.py" ;;
      2:--ci) exec python3 "$root/scripts/check-governance-drift.py" --ci ;;
      *) echo "$usage" >&2; exit 2 ;;
    esac ;;
  --validate) exec python3 "$root/scripts/check-governance-drift.py" ;;
  "") ;;
  *) echo "$usage" >&2; exit 2 ;;
esac
if ! command -v kt-iskelet >/dev/null 2>&1; then
  echo "yazma kipi yerel ajan uzlaştırması veya isteğe bağlı yerel CLI gerektirir" >&2
  exit 2
fi
public_mode="yaz"
[ "$mode" = "check" ] && public_mode="denetle"
exec kt-iskelet yansit --hedef-dizin "$root" --kip "$public_mode"
