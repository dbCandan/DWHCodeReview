#!/usr/bin/env bash
# Azure job supplies KUBECONFIG and runs Helm. Usage: deploy.sh [--render|--apply]
set +x
set -euo pipefail

chart="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
release="${RELEASE:-dwhcodereview}"
namespace="${NAMESPACE:-dwhcodereview}"
# Deploy the image of the checked-out commit: the build workflow tags each image with the full commit
# SHA and the pipeline waits for that tag. A fixed tag such as "latest" leaves the Deployment
# unchanged, so Kubernetes would keep running the old pod. IMAGE_TAG still overrides it.
image_tag="${IMAGE_TAG:-$(git -C "$chart" rev-parse HEAD 2>/dev/null || echo latest)}"
echo "image tag: $image_tag" >&2
mode=apply

while [[ $# -gt 0 ]]; do
  case "$1" in
    --render) mode=render; shift ;;
    --apply) mode=apply; shift ;;
    --release) release="$2"; shift 2 ;;
    --namespace) namespace="$2"; shift 2 ;;
    --values) shift 2 ;;
    *) echo 'Usage: deploy.sh [--render|--apply]' >&2; exit 2 ;;
  esac
done

common=(--values "$chart/values.yaml" --values "$chart/values-project.yaml"
  --namespace "$namespace" --set-string "app.image.tag=$image_tag")

if [[ "$mode" == render ]]; then
  exec helm template "$release" "$chart" "${common[@]}"
fi

kubectl get namespace "$namespace" >/dev/null 2>&1 || kubectl create namespace "$namespace"

# The shared wildcard TLS Secret is namespace-scoped; copy it once from the source namespace.
if ! kubectl --namespace "$namespace" get secret ailab-tls >/dev/null 2>&1; then
  src_ns="${TLS_SOURCE_NAMESPACE:-kt-verim}"
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT; umask 077
  kubectl --namespace "$src_ns" get secret ailab-tls --output 'jsonpath={.data.tls\.crt}' | base64 -d > "$tmp/tls.crt"
  kubectl --namespace "$src_ns" get secret ailab-tls --output 'jsonpath={.data.tls\.key}' | base64 -d > "$tmp/tls.key"
  kubectl --namespace "$namespace" create secret tls ailab-tls --cert="$tmp/tls.crt" --key="$tmp/tls.key" >/dev/null
fi

# A release left pending by an interrupted run would block the upgrade: roll it back or remove it.
status="$(helm --namespace "$namespace" status "$release" -o json 2>/dev/null | sed -nE 's/.*"status":"([^"]+)".*/\1/p' | head -n 1 || true)"
case "$status" in
  pending-install) helm uninstall "$release" --namespace "$namespace" || true ;;
  pending-upgrade|pending-rollback) helm rollback "$release" --namespace "$namespace" || true ;;
esac

exec helm upgrade --install "$release" "$chart" --create-namespace --atomic --wait \
  --timeout "${HELM_TIMEOUT:-10m}" "${common[@]}"
