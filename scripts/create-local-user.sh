#!/usr/bin/env sh
set -eu

# Create or reset a local test account for one application role in the local Compose stack.
# Usage: scripts/create-local-user.sh --role inceleyici
# The backend refuses the command while the directory is enabled or outside the local environment.
root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
role=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --role)
      [ "$#" -ge 2 ] || { echo "--role bir değer ister: inceleyici" >&2; exit 2; }
      role="$2"
      shift 2
      ;;
    *)
      echo "kullanım: scripts/create-local-user.sh --role inceleyici" >&2
      exit 2
      ;;
  esac
done
case "$role" in
  inceleyici) ;;
  *)
    echo "kullanım: scripts/create-local-user.sh --role inceleyici" >&2
    exit 2
    ;;
esac

username="${DWHCODEREVIEW_LOCAL_USER_NAME:-}"
password="${DWHCODEREVIEW_LOCAL_USER_PASS:-}"
if [ -z "$username" ]; then
  printf "Yerel test kullanıcı adı: "
  IFS= read -r username
fi
if [ -z "$password" ]; then
  printf "Parola (en az 15 karakter): "
  trap 'stty echo 2>/dev/null || true' EXIT HUP INT TERM
  stty -echo
  IFS= read -r password
  stty echo
  trap - EXIT HUP INT TERM
  printf "\n"
fi

# app/backend/app/core/security.py owns the password policy; the backend rejects a weak password.
printf '%s\n' "$password" | "$root/scripts/stack.sh" exec -T \
  backend python -m app.scripts.create_local_user --username "$username" --role "$role" --password-stdin
