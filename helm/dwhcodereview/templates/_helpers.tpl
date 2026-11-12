{{- define "generated.resourceName" -}}
{{- $root := index . 0 -}}
{{- $component := index . 1 -}}
{{- $release := $root.Release.Name | trunc 18 | trimSuffix "-" -}}
{{- $slug := $root.Chart.Name | trunc 18 | trimSuffix "-" -}}
{{- $identity := printf "%s/%s/%s/%s" $root.Release.Namespace $root.Release.Name $root.Chart.Name $component -}}
{{- printf "%s-%s-%s-%s" $release $slug $component (sha256sum $identity | trunc 12) | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{- define "generated.workloadLabels" -}}
app.kubernetes.io/name: {{ .root.Chart.Name | quote }}
app.kubernetes.io/part-of: {{ .root.Chart.Name | quote }}
app.kubernetes.io/instance: {{ .root.Release.Name | quote }}
app.kubernetes.io/component: {{ .component | quote }}
scaffold.kt.internal/workload: {{ include "generated.resourceName" (list .root .component) | quote }}
{{- end }}

{{- define "generated.annotations" -}}
scaffold.kt.internal/product-name: {{ index .Chart.Annotations "scaffold.kt.internal/product-name" | quote }}
scaffold.kt.internal/product-slug: {{ .Chart.Name | quote }}
scaffold.kt.internal/release-namespace: {{ .Release.Namespace | quote }}
{{- end }}

{{- define "generated.image" -}}
{{- $component := index . 0 -}}
{{- $image := index . 1 -}}
{{- $repository := required (printf "%s.image.repository is required" $component) $image.repository -}}
{{- $digest := default "" $image.digest -}}
{{- if $digest -}}
{{- if not (regexMatch "^sha256:[0-9a-f]{64}$" $digest) -}}
{{- fail (printf "%s.image.digest must be a lowercase sha256 digest" $component) -}}
{{- end -}}
{{- printf "%s@%s" $repository $digest -}}
{{- else -}}
{{- $tag := required (printf "%s.image.tag is required when digest is empty" $component) $image.tag -}}
{{- if not (regexMatch "^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$" $tag) -}}
{{- fail (printf "%s.image.tag must be a valid OCI tag" $component) -}}
{{- end -}}
{{- printf "%s:%s" $repository $tag -}}
{{- end -}}
{{- end }}

{{- define "generated.postgresImage" -}}
{{- $image := .Values.postgres.image -}}
{{- $repository := required "postgres.image.repository is required" $image.repository -}}
{{- $digest := required "postgres.image.digest must pin the PostgreSQL image when postgres.enabled" $image.digest -}}
{{- if not (regexMatch "^sha256:[0-9a-f]{64}$" $digest) -}}
{{- fail "postgres.image.digest must be a lowercase sha256 digest" -}}
{{- end -}}
{{- printf "%s@%s" $repository $digest -}}
{{- end }}

{{- define "generated.validateMigration" -}}
{{- if not .Values.postgres.enabled -}}
{{- fail "migration.enabled requires postgres.enabled; the migration Job reaches only the in-chart PostgreSQL" -}}
{{- end -}}
{{- end }}

{{- define "generated.validateDatabase" -}}
{{- if not .Values.migration.enabled -}}
{{- fail "postgres.enabled requires migration.enabled; the migration Job creates the runtime role the backend connects with" -}}
{{- end -}}
{{- end }}

{{/*
Secrets of the in-chart database. The chart only names them; deploy.sh generates their values once
and reuses them from the cluster. The database and the migration own the schema owner connection;
the backend sees only the DML-only runtime connection.
*/}}
{{- define "generated.postgresSecret" -}}
{{- printf "%s-postgres" .Release.Name -}}
{{- end }}

{{- define "generated.migrationSecret" -}}
{{- printf "%s-migration" .Release.Name -}}
{{- end }}

{{- define "generated.databaseSecret" -}}
{{- printf "%s-database" .Release.Name -}}
{{- end }}

{{/*
Migration mode. "upgrade" when an earlier release already created the migration NetworkPolicy, so
the database exists and the Job runs as a pre-upgrade hook before any new backend pod. Otherwise
"bootstrap": the Job is an ordinary release resource created together with the database (fresh
install, or the first upgrade that adds the database), so nothing waits on backend readiness first.
helm template sees no cluster and always renders "bootstrap".
*/}}
{{- define "generated.migrationMode" -}}
{{- if lookup "networking.k8s.io/v1" "NetworkPolicy" .Release.Namespace (include "generated.resourceName" (list . "migration")) -}}
upgrade
{{- else -}}
bootstrap
{{- end -}}
{{- end }}

{{/*
backend.config carries only non-secret, prefixed settings; secrets and the database connection
arrive through envFrom, which an env entry would otherwise override.
*/}}
{{- define "generated.validateBackendConfig" -}}
{{- range $key, $value := .Values.backend.config -}}
{{- if not (regexMatch "^DWHCODEREVIEW_[A-Z0-9_]+$" $key) -}}
{{- fail (printf "backend.config key %s must be an upper-case DWHCODEREVIEW_ setting" $key) -}}
{{- end -}}
{{- if regexMatch "PASSW|SECRET|CREDENTIAL|PRIVATE_KEY|API_KEY|DATABASE_URL|DSN|(TOKEN|KEY)$" $key -}}
{{- fail (printf "backend.config key %s looks secret; put it in the project Secret" $key) -}}
{{- end -}}
{{- if kindIs "map" $value -}}
{{- fail (printf "backend.config value of %s must be a scalar" $key) -}}
{{- end -}}
{{- if kindIs "slice" $value -}}
{{- fail (printf "backend.config value of %s must be a scalar" $key) -}}
{{- end -}}
{{- end -}}
{{- end }}
