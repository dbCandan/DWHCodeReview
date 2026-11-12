#!/usr/bin/env bash
# GitHub publishes images; the existing Azure job supplies KUBECONFIG and runs Helm.
# Two optional project-owned files sit beside this script and are never written by the scaffold:
#   values-project.yaml  project environment addressing, layered over the base values; no secrets
#   deploy-hooks.sh      project Secret preparation, run by apply before any Helm change
set +x
set -euo pipefail

chart="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
release="${RELEASE:-dwhcodereview}"
namespace="${NAMESPACE:-dwhcodereview}"
values_file="${VALUES_FILE:-$chart/values.yaml}"
project_values="$chart/values-project.yaml"
project_hook="$chart/deploy-hooks.sh"
image_tag="${IMAGE_TAG:-latest}"
mode=apply

usage() {
  echo 'Usage: helm/dwhcodereview/deploy.sh [--render|--apply] [--values <values.yaml>] [--release <name>] [--namespace <name>]' >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --render) mode=render; shift ;;
    --apply) mode=apply; shift ;;
    --values) [[ $# -ge 2 ]] || { usage; exit 2; }; values_file="$2"; shift 2 ;;
    --release) [[ $# -ge 2 ]] || { usage; exit 2; }; release="$2"; shift 2 ;;
    --namespace) [[ $# -ge 2 ]] || { usage; exit 2; }; namespace="$2"; shift 2 ;;
    --help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done

[[ -n "$values_file" && -f "$values_file" ]] || { usage; exit 2; }
[[ "$release" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] || { usage; exit 2; }
[[ "$namespace" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] || { usage; exit 2; }

if [[ "$image_tag" == latest ]] && \
  { [[ "${BUILD_SOURCEVERSION+x}" == x ]] || [[ "${TF_BUILD:-}" =~ ^[tT][rR][uU][eE]$ ]]; }; then
  [[ "${BUILD_SOURCEVERSION:-}" =~ ^[0123456789abcdef]{40}$ ]] || {
    echo 'BUILD_SOURCEVERSION must contain exactly 40 lowercase hexadecimal characters' >&2
    exit 2
  }
  image_tag="$BUILD_SOURCEVERSION"
elif [[ ! "$image_tag" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; then
  echo 'IMAGE_TAG must be a valid OCI tag' >&2
  exit 2
fi

image_args=(
  --set-string "backend.image.tag=$image_tag"
  --set-string backend.image.digest=
  --set-string "frontend.image.tag=$image_tag"
  --set-string frontend.image.digest=
)
values_args=(--values "$values_file")
if [[ -e "$project_values" ]]; then
  [[ -f "$project_values" && ! -L "$project_values" ]] || {
    echo 'values-project.yaml must be a regular file' >&2
    exit 2
  }
  values_args+=(--values "$project_values")
fi
common=("${values_args[@]}" --namespace "$namespace" "${image_args[@]}")

helm lint "$chart" "${common[@]}" >&2
if [[ "$mode" == render ]]; then
  exec helm template "$release" "$chart" "${common[@]}"
fi

# Registry answer for one rendered image: 0 published, 1 absent, 2 not established.
# The GHCR proxy cache answers anonymous pulls with a bearer challenge; the token
# never reaches the log.
registry_manifest_state() {
  local reference="$1" name reference_tag host repository url code challenge realm service scope token
  local accept='application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json'
  if [[ "$reference" == *@* ]]; then
    name="${reference%@*}"; reference_tag="${reference##*@}"
  else
    name="${reference%:*}"; reference_tag="${reference##*:}"
  fi
  host="${name%%/*}"; repository="${name#*/}"
  [[ -n "$reference_tag" && "$host" != "$name" ]] || return 2
  url="https://$host/v2/$repository/manifests/$reference_tag"
  challenge="$(curl --silent --max-time 20 --head --output /dev/null --dump-header - \
    --header "Accept: $accept" "$url" 2>/dev/null | tr -d '\r')" || return 2
  code="$(sed -nE 's#^HTTP/[0-9.]+ ([0-9]{3}).*#\1#p' <<< "$challenge" | tail -n 1)"
  if [[ "$code" == 401 ]]; then
    challenge="$(grep -i '^www-authenticate: *bearer ' <<< "$challenge" | head -n 1)"
    realm="$(sed -nE 's/.*realm="([^"]+)".*/\1/p' <<< "$challenge")"
    service="$(sed -nE 's/.*service="([^"]+)".*/\1/p' <<< "$challenge")"
    scope="$(sed -nE 's/.*scope="([^"]+)".*/\1/p' <<< "$challenge")"
    [[ "$realm" == https://* ]] || return 2
    token="$(curl --silent --max-time 20 --get "$realm" --data-urlencode "service=$service" \
      --data-urlencode "scope=$scope" 2>/dev/null \
      | sed -nE 's/.*"(token|access_token)"[[:space:]]*:[[:space:]]*"([^"]+)".*/\2/p' | head -n 1)"
    [[ -n "$token" ]] || return 2
    code="$(curl --silent --max-time 20 --head --output /dev/null --write-out '%{http_code}' \
      --header "Accept: $accept" --header "Authorization: Bearer $token" "$url" 2>/dev/null)" \
      || return 2
  fi
  case "$code" in
    200) return 0 ;;
    404) return 1 ;;
    *) return 2 ;;
  esac
}

# Azure starts on the same push that GitHub builds, and a failed scan never publishes.
# Wait for every rendered image before any cluster change; a missing image stops here.
# When the registry cannot answer, Helm still keeps the ready pods of the last release.
wait_for_published_images() {
  local references reference state missing unknown deadline
  references="$(sed -nE 's/^[[:space:]]*image:[[:space:]]*"?([^"[:space:]]+)"?[[:space:]]*$/\1/p' \
    <<< "$rendered" | sort -u)"
  [[ -n "$references" ]] || { echo '[IMAGE] no workload image was rendered' >&2; return 1; }
  if ! command -v curl >/dev/null; then
    echo '[IMAGE] UNKNOWN curl is unavailable; publication was not checked' >&2
    return 0
  fi
  deadline=$((SECONDS + ${IMAGE_WAIT_SECONDS:-1200}))
  while :; do
    missing=""; unknown=""
    for reference in $references; do
      state=0
      registry_manifest_state "$reference" || state=$?
      case "$state" in
        0) ;;
        1) missing="$missing $reference" ;;
        *) unknown="$unknown $reference" ;;
      esac
    done
    if [[ -z "$missing" ]]; then
      if [[ -n "$unknown" ]]; then
        echo "[IMAGE] UNKNOWN the registry did not answer for:$unknown" >&2
      else
        echo '[IMAGE] PUBLISHED every rendered image'
      fi
      return 0
    fi
    (( SECONDS < deadline )) || break
    echo "[IMAGE] WAITING for:$missing"
    sleep "${IMAGE_POLL_SECONDS:-30}"
  done
  echo "[IMAGE] MISSING$missing; the build did not publish them, no cluster change was made" >&2
  return 1
}

release_field() {
  local state pattern
  state="$(helm --namespace "$namespace" list --all --filter "^${release}$" --output json \
    2>/dev/null || true)"
  pattern="\"$1\"[[:space:]]*:[[:space:]]*\"([^\"]*)\""
  if [[ "$state" =~ $pattern ]]; then printf '%s' "${BASH_REMATCH[1]}"; fi
}

# A pending release is either another run's live operation or an interrupted one.
# Wait for a live operation to settle; recover an interrupted upgrade by rollback,
# which keeps the served workloads. Only a never-installed release is uninstalled.
settle_pending_release() {
  local status updated started limit
  status="$(release_field status)"
  [[ "$status" == pending-* ]] || return 0
  limit="${PENDING_WAIT_SECONDS:-1800}"
  updated="$(release_field updated)"
  # GNU date reads an empty value as midnight, so only a reported time is aged.
  if [[ -n "$updated" ]] && started="$(date -u -d "${updated% UTC}" +%s 2>/dev/null)"; then
    limit=$(( limit - ($(date -u +%s) - started) ))
  fi
  local deadline=$((SECONDS + (limit > 0 ? limit : 0)))
  while [[ "$status" == pending-* ]] && (( SECONDS < deadline )); do
    echo "[RELEASE] $status; waiting for the running deployment to finish"
    sleep "${PENDING_POLL_SECONDS:-20}"
    status="$(release_field status)"
  done
  case "$status" in
    pending-install)
      echo '[RELEASE] pending-install never served; removing it'
      helm uninstall "$release" --namespace "$namespace" --wait || return 1
      ;;
    pending-upgrade|pending-rollback)
      echo "[RELEASE] $status is interrupted; rolling back to the last release"
      helm rollback "$release" --namespace "$namespace" --wait --timeout "${HELM_TIMEOUT:-30m}" || {
        echo "[RELEASE] rollback failed; the release is left in place for an operator" >&2
        return 1
      }
      ;;
  esac
}

# One key of a Secret in the release namespace, empty when the Secret or the key is absent. A read
# that fails stops the caller, so an unreadable Secret is never mistaken for a missing one and
# replaced. The value is never printed.
secret_value() {
  local encoded
  encoded="$(kubectl --namespace "$namespace" get secret "$1" --ignore-not-found \
    --output "jsonpath={.data.$2}")" || return 1
  [[ -z "$encoded" ]] || base64 --decode <<< "$encoded"
}

# Writes one Secret from files named after its keys; values never appear as arguments or in logs.
write_secret() {
  local name="$1" directory="$2" key sources=()
  for key in "$directory"/*; do sources+=("--from-file=${key##*/}=$key"); done
  kubectl --namespace "$namespace" create secret generic "$name" "${sources[@]}" \
    --dry-run=client --output yaml | kubectl apply --filename - >/dev/null
}

# When the rendered chart runs the in-chart database, the release needs three Secrets:
#   <release>-postgres   POSTGRES_USER, POSTGRES_PASSWORD (schema owner, read by the database)
#   <release>-migration  DWHCODEREVIEW_DATABASE_URL and PG* keys of the schema owner, plus
#                        RUNTIME_DATABASE_USER and RUNTIME_DATABASE_PASSWORD for the runtime role
#   <release>-database   DWHCODEREVIEW_DATABASE_URL of the DML-only runtime role (backend only)
# Credentials are generated on the first run and read back from the cluster afterwards, so a
# password a volume or a project hook already holds is kept. Only the address is re-derived.
ensure_database_secrets() {
  local manifest host port database owner owner_password runtime runtime_password state=reused
  manifest="$(awk '/^---/ { if (found) exit; document = ""; next }
    { document = document $0 "\n" } /^kind: StatefulSet$/ { found = 1 }
    END { if (found) printf "%s", document }' <<< "$rendered")"
  [[ -n "$manifest" ]] || return 0
  host="$(sed -nE 's/^  serviceName: ([a-z0-9-]+)$/\1/p' <<< "$manifest" | head -n 1)"
  port="$(sed -nE 's/.*[{ ]containerPort: ([0-9]+)[,}].*/\1/p' <<< "$manifest" | head -n 1)"
  database="$(sed -nE 's/.*name: POSTGRES_DB, value: "([A-Za-z0-9_]+)".*/\1/p' <<< "$manifest" \
    | head -n 1)"
  [[ -n "$host" && -n "$port" && -n "$database" ]] || {
    echo '[DATABASE] the rendered database address is incomplete' >&2
    return 1
  }

  if ! owner="$(secret_value "$release-postgres" POSTGRES_USER)" \
    || ! owner_password="$(secret_value "$release-postgres" POSTGRES_PASSWORD)" \
    || ! runtime="$(secret_value "$release-migration" RUNTIME_DATABASE_USER)" \
    || ! runtime_password="$(secret_value "$release-migration" RUNTIME_DATABASE_PASSWORD)"; then
    echo '[DATABASE] the existing database Secrets could not be read; nothing was changed' >&2
    return 1
  fi
  if [[ -z "$owner" || -z "$owner_password" || -z "$runtime" || -z "$runtime_password" ]]; then
    state=generated
  fi
  owner="${owner:-app_owner}"
  runtime="${runtime:-app_runtime}"
  [[ -n "$owner_password" ]] || owner_password="$(new_password)"
  [[ -n "$runtime_password" ]] || runtime_password="$(new_password)"
  [[ "$owner" =~ ^[a-z_][a-z0-9_]{0,62}$ && "$runtime" =~ ^[a-z_][a-z0-9_]{0,62}$ \
    && "$owner" != "$runtime" ]] || {
    echo '[DATABASE] database user names must be distinct lowercase PostgreSQL names' >&2
    return 1
  }
  [[ "$owner_password" =~ ^[A-Za-z0-9._~-]{16,}$ \
    && "$runtime_password" =~ ^[A-Za-z0-9._~-]{16,}$ ]] || {
    echo '[DATABASE] database passwords must hold at least 16 URL-safe characters' >&2
    return 1
  }

  rm -rf "$work/postgres" "$work/migration" "$work/database"
  mkdir "$work/postgres" "$work/migration" "$work/database"
  printf '%s' "$owner" > "$work/postgres/POSTGRES_USER"
  printf '%s' "$owner_password" > "$work/postgres/POSTGRES_PASSWORD"
  printf 'postgresql+asyncpg://%s:%s@%s:%s/%s' "$owner" "$owner_password" "$host" "$port" \
    "$database" > "$work/migration/DWHCODEREVIEW_DATABASE_URL"
  printf '%s' "$host" > "$work/migration/PGHOST"
  printf '%s' "$port" > "$work/migration/PGPORT"
  printf '%s' "$database" > "$work/migration/PGDATABASE"
  printf '%s' "$owner" > "$work/migration/PGUSER"
  printf '%s' "$owner_password" > "$work/migration/PGPASSWORD"
  printf '%s' "$runtime" > "$work/migration/RUNTIME_DATABASE_USER"
  printf '%s' "$runtime_password" > "$work/migration/RUNTIME_DATABASE_PASSWORD"
  printf 'postgresql+asyncpg://%s:%s@%s:%s/%s' "$runtime" "$runtime_password" "$host" "$port" \
    "$database" > "$work/database/DWHCODEREVIEW_DATABASE_URL"
  write_secret "$release-postgres" "$work/postgres" || return 1
  write_secret "$release-migration" "$work/migration" || return 1
  write_secret "$release-database" "$work/database" || return 1
  echo "[DATABASE] credentials $state: $release-postgres, $release-migration, $release-database"
}

new_password() {
  od -An -N24 -tx1 /dev/urandom | tr -d ' \n'
}

# The optional project hook prepares project Secrets (for example a signing key generated once and
# reused, or optional external credentials) with the runner's identity. It runs only in apply mode,
# after the namespace exists and before any Helm change; a failure stops the deployment there.
run_project_hook() {
  [[ -e "$project_hook" ]] || return 0
  [[ -f "$project_hook" && ! -L "$project_hook" ]] || {
    echo '[HOOK] deploy-hooks.sh must be a regular file' >&2
    return 1
  }
  echo '[HOOK] running the project deploy hook'
  KT_DEPLOY_RELEASE="$release" KT_DEPLOY_NAMESPACE="$namespace" KT_DEPLOY_CHART_DIR="$chart" \
    KT_DEPLOY_IMAGE_TAG="$image_tag" KT_DEPLOY_DATABASE_ENABLED="$database_enabled" \
    bash "$project_hook" || {
    echo '[HOOK] the project deploy hook failed; no Helm change was made' >&2
    return 1
  }
}

command -v kubectl >/dev/null || {
  echo 'kubectl is required for deployment' >&2
  exit 1
}
rendered="$(helm template "$release" "$chart" "${common[@]}")" || exit 1
database_enabled=false
if grep -qx 'kind: StatefulSet' <<< "$rendered"; then database_enabled=true; fi
wait_for_published_images || exit 1
kubectl get namespace "$namespace" >/dev/null 2>&1 || kubectl create namespace "$namespace"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
umask 077

# The shared wildcard TLS Secret is namespace-scoped. The established nonprod
# runner may copy its public certificate and private key into a new application
# namespace without putting either value in Git, Helm arguments or logs.
if [[ "${TF_BUILD:-}" =~ ^[tT][rR][uU][eE]$ ]] \
  && [[ "${TLS_COPY_ENABLED:-true}" == true ]]; then
  tls_source_namespace="${TLS_SOURCE_NAMESPACE:-kt-verim}"
  tls_source_secret="${TLS_SOURCE_SECRET:-ailab-tls}"
  tls_target_secret="${TLS_TARGET_SECRET:-ailab-tls}"
  if ! kubectl --namespace "$namespace" get secret "$tls_target_secret" >/dev/null 2>&1; then
    command -v openssl >/dev/null || {
      echo 'openssl is required to copy the shared TLS Secret' >&2
      exit 1
    }
    temporary="$work/tls"
    mkdir "$temporary"
    kubectl --namespace "$tls_source_namespace" get secret "$tls_source_secret" \
      --output 'jsonpath={.data.tls\.crt}' | openssl base64 -d -A > "$temporary/tls.crt"
    kubectl --namespace "$tls_source_namespace" get secret "$tls_source_secret" \
      --output 'jsonpath={.data.tls\.key}' | openssl base64 -d -A > "$temporary/tls.key"
    [[ -s "$temporary/tls.crt" && -s "$temporary/tls.key" ]] || {
      echo 'shared TLS source is incomplete' >&2
      exit 1
    }
    kubectl --namespace "$namespace" create secret tls "$tls_target_secret" \
      --cert="$temporary/tls.crt" --key="$temporary/tls.key" >/dev/null
  fi
fi

run_project_hook || exit 1
ensure_database_secrets || exit 1
rm -rf "$work"
trap - EXIT
settle_pending_release || exit 1

# --wait-for-jobs makes a failed schema migration fail the release, so --atomic restores the last one.
exec helm upgrade --install "$release" "$chart" \
  --create-namespace --reset-values --atomic --wait --wait-for-jobs \
  --timeout "${HELM_TIMEOUT:-30m}" "${common[@]}"
