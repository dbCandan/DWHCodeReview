{{/*
Resource name: the release name, or "<release>-<chart>" when the release does not already carry the
chart name. Kubernetes names are at most 63 characters.
*/}}
{{- define "app.name" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end }}

{{/*
Labels shared by every resource. They are also the Deployment and Service selector, so they hold only
values that never change between releases (no chart or app version).
*/}}
{{- define "app.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name | quote }}
app.kubernetes.io/instance: {{ .Release.Name | quote }}
{{- end }}

{{/*
Container image: "repository@sha256:..." when a digest is set, otherwise "repository:tag".
*/}}
{{- define "app.image" -}}
{{- $image := .Values.app.image -}}
{{- $repository := required "app.image.repository is required" $image.repository -}}
{{- $digest := default "" $image.digest -}}
{{- if $digest -}}
{{- if not (regexMatch "^sha256:[0-9a-f]{64}$" $digest) -}}
{{- fail "app.image.digest must be a lowercase sha256 digest" -}}
{{- end -}}
{{- printf "%s@%s" $repository $digest -}}
{{- else -}}
{{- $tag := required "app.image.tag is required when app.image.digest is empty" $image.tag | toString -}}
{{- if not (regexMatch "^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$" $tag) -}}
{{- fail "app.image.tag must be a valid OCI tag" -}}
{{- end -}}
{{- printf "%s:%s" $repository $tag -}}
{{- end -}}
{{- end }}
