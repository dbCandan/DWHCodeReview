#!/usr/bin/env bash
# Project deploy hook (rules/45-dagitim-hedefi.md). deploy.sh runs it only in apply mode, after the
# image check, the namespace and ailab-tls, and before the database Secrets and any Helm change.
# It prepares the runtime Secret the backend reads (backend.existingSecret in values-project.yaml)
# so a nonprod deployment needs no operator-supplied secret:
#   DWHCODEREVIEW_JWT_PRIVATE_KEY  pipeline JWT_PRIVATE_KEY, else the cluster value, else a P-256
#                                  key generated once
#   DWHCODEREVIEW_SETTINGS_ENCRYPTION_KEY
#                                  pipeline SETTINGS_ENCRYPTION_KEY, else the cluster value, else
#                                  32 random bytes in base64 generated once; it encrypts the SQL
#                                  Server password the super admin saves in the application
#                                  (specs/sql-review/PRDs/002-sql-server-connection Requirement 10)
#   DWHCODEREVIEW_MSSQL_USER       pipeline MSSQL_USER, else the cluster value, else absent
#   DWHCODEREVIEW_MSSQL_PASSWORD   pipeline MSSQL_PASSWORD, else the cluster value, else absent
#   DWHCODEREVIEW_LLM_API_KEY      pipeline LLM_API_KEY, else the cluster value, else absent
#   DWHCODEREVIEW_SMTP_USERNAME    pipeline SMTP_USER, else the cluster value, else absent
#   DWHCODEREVIEW_SMTP_PASSWORD    pipeline SMTP_PASSWORD, else the cluster value, else absent;
#                                  the corporate relay login of the scheduled review e-mail
#                                  (specs/sql-review/PRDs/008-scheduled-review-email)
#   DWHCODEREVIEW_BOOTSTRAP_SUPER_ADMIN_PASSWORD
#                                  pipeline DWHCODEREVIEW_ADMIN_PASSWORD, else the cluster value,
#                                  else absent; the backend creates the super admin with it once
#                                  and never resets an existing account
#                                  (specs/application-foundation/PRDs/001-directory-login
#                                  Requirement 14)
# An empty variable or an unresolved Azure macro such as $(MSSQL_USER) counts as not provided.
# Other keys already in the Secret are left untouched. Values reach kubectl only through files in
# an owner-only temporary directory; the log names keys, never values.
# Contract: specs/application-foundation/PRDs/002-kubernetes-delivery/PRD.md (Requirement 5).
set +x
set -euo pipefail

namespace="${KT_DEPLOY_NAMESPACE:?KT_DEPLOY_NAMESPACE is required}"
release="${KT_DEPLOY_RELEASE:?KT_DEPLOY_RELEASE is required}"
image_tag="${KT_DEPLOY_IMAGE_TAG:-}"
# Must equal backend.existingSecret in values-project.yaml.
secret=dwhcodereview-runtime
unresolved_macro='^\$\([A-Za-z0-9_.]+\)$'

umask 077
work="$(mktemp -d "${TMPDIR:-/tmp}/dwhcodereview-hook.XXXXXXXX")"
trap 'rm -rf -- "$work"' EXIT
mkdir "$work/keys"

fail() {
  echo "[RUNTIME] $1; no Helm change was made" >&2
  exit 1
}

# The current cluster value of one key, written to a file; returns 1 when the key is absent. A read
# that fails stops the hook, so an unreadable Secret is never mistaken for a missing one.
cluster_value() {
  local key="$1" target="$2" encoded
  encoded="$(kubectl --namespace "$namespace" get secret "$secret" --ignore-not-found \
    --output "jsonpath={.data.$key}")" || fail "Secret $secret could not be read"
  [[ -n "$encoded" ]] || return 1
  base64 --decode <<< "$encoded" > "$target" || fail "Secret $secret holds an undecodable $key"
}

# 0 when the pipeline variable holds a usable value; unresolved Azure macros count as absent.
pipeline_provides() {
  local name="$1"
  [[ -n "${!name:-}" ]] || return 1
  if [[ "${!name}" =~ $unresolved_macro ]]; then
    echo "[RUNTIME] $name is an unresolved Azure variable; treated as not provided"
    return 1
  fi
}

# A usable ES256 signing key: a P-256 elliptic-curve private key. Only the public part is printed
# for the check, so no private material passes through a pipe.
valid_signing_key() {
  local text
  text="$(openssl pkey -in "$1" -pubout 2>/dev/null \
    | openssl pkey -pubin -noout -text 2>/dev/null)" || return 1
  [[ "$text" == *prime256v1* || "$text" == *P-256* ]]
}

# A usable settings encryption key: standard base64 of exactly 32 bytes (44 characters). The value
# is compared inside the shell only; nothing is printed.
valid_encryption_key() {
  local value
  value="$(cat "$1")" || return 1
  [[ "$value" =~ ^[A-Za-z0-9+/]{43}=$ ]]
}

changed=()
# settle <secret key> <pipeline variable> <signing-key|encryption-key|optional>
settle() {
  local key="$1" variable="$2" kind="$3" target="$work/keys/$1" current="$work/current-$1" state
  local present=false
  if cluster_value "$key" "$current"; then present=true; fi
  if pipeline_provides "$variable"; then
    printf '%s' "${!variable}" > "$target"
    if [[ "$kind" == signing-key ]]; then
      command -v openssl >/dev/null || fail 'openssl is required to check JWT_PRIVATE_KEY'
      valid_signing_key "$target" || fail "$variable must be a PEM P-256 private key"
    elif [[ "$kind" == encryption-key ]]; then
      valid_encryption_key "$target" || fail "$variable must be base64 of exactly 32 bytes"
    fi
    state="set from $variable"
  elif [[ "$present" == true ]]; then
    cp "$current" "$target"
    state=kept
  elif [[ "$kind" == signing-key ]]; then
    command -v openssl >/dev/null || fail 'openssl is required to generate the signing key'
    openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$target" 2>/dev/null \
      || fail 'the signing key could not be generated'
    state=generated
  elif [[ "$kind" == encryption-key ]]; then
    command -v openssl >/dev/null || fail 'openssl is required to generate the encryption key'
    openssl rand -base64 32 2>/dev/null | tr -d '\n' > "$target"
    valid_encryption_key "$target" || fail 'the encryption key could not be generated'
    state=generated
  else
    echo "[RUNTIME] $key not provided; $variable is absent"
    return 0
  fi
  if [[ "$present" != true ]] || ! cmp -s "$current" "$target"; then changed+=("$key"); fi
  echo "[RUNTIME] $key $state"
}

settle DWHCODEREVIEW_JWT_PRIVATE_KEY JWT_PRIVATE_KEY signing-key
settle DWHCODEREVIEW_SETTINGS_ENCRYPTION_KEY SETTINGS_ENCRYPTION_KEY encryption-key
settle DWHCODEREVIEW_MSSQL_USER MSSQL_USER optional
settle DWHCODEREVIEW_MSSQL_PASSWORD MSSQL_PASSWORD optional
settle DWHCODEREVIEW_LLM_API_KEY LLM_API_KEY optional
settle DWHCODEREVIEW_SMTP_USERNAME SMTP_USER optional
settle DWHCODEREVIEW_SMTP_PASSWORD SMTP_PASSWORD optional
settle DWHCODEREVIEW_BOOTSTRAP_SUPER_ADMIN_PASSWORD DWHCODEREVIEW_ADMIN_PASSWORD optional
if [[ -s "$work/keys/DWHCODEREVIEW_MSSQL_USER" ]] \
  && LC_ALL=C grep -q '[[:cntrl:]]' "$work/keys/DWHCODEREVIEW_MSSQL_USER"; then
  fail 'MSSQL_USER must not contain control characters'
fi
if [[ -s "$work/keys/DWHCODEREVIEW_SMTP_USERNAME" ]] \
  && LC_ALL=C grep -q '[[:cntrl:]]' "$work/keys/DWHCODEREVIEW_SMTP_USERNAME"; then
  fail 'SMTP_USER must not contain control characters'
fi

if [[ ${#changed[@]} -eq 0 ]]; then
  echo "[RUNTIME] Secret $secret unchanged"
  exit 0
fi

# kubectl apply merges only the keys named here, so older keys of the Secret are kept. API errors
# may echo submitted data, so only a fixed message reaches the log.
sources=()
for file in "$work"/keys/*; do sources+=("--from-file=${file##*/}=$file"); done
kubectl --namespace "$namespace" create secret generic "$secret" "${sources[@]}" \
  --dry-run=client --output yaml > "$work/secret.yaml" 2>/dev/null \
  || fail "Secret $secret could not be prepared"
kubectl apply --filename "$work/secret.yaml" >/dev/null 2>&1 \
  || fail "Secret $secret could not be written"
echo "[RUNTIME] Secret $secret written: ${changed[*]}"

# A new Secret value reaches the process only through a new pod. When Helm keeps the backend pod
# template (the same image tag is already running), restart the backend here.
backend="$(kubectl --namespace "$namespace" get deployment \
  --selector "app.kubernetes.io/instance=$release,app.kubernetes.io/component=backend" \
  --output 'jsonpath={range .items[*]}{.metadata.name}{"\t"}{.spec.template.spec.containers[0].image}{"\n"}{end}')" \
  || fail 'the backend Deployment could not be read'
while IFS=$'\t' read -r name image; do
  [[ -n "$name" && -n "$image_tag" && "$image" == *":$image_tag" ]] || continue
  echo "[RUNTIME] restarting $name so it reads the new Secret"
  kubectl --namespace "$namespace" rollout restart "deployment/$name" >/dev/null \
    || fail "$name could not be restarted"
  kubectl --namespace "$namespace" rollout status "deployment/$name" \
    --timeout "${HELM_TIMEOUT:-30m}" || fail "$name did not become ready after the restart"
done <<< "$backend"
