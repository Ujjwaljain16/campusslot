{{/* Chart name, truncated to the 63 characters Kubernetes allows. */}}
{{- define "campusslot.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Fully qualified name used as a prefix for every resource. */}}
{{- define "campusslot.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* Labels shared by every resource. */}}
{{- define "campusslot.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/name: {{ include "campusslot.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/* Labels that select the pods of one component. Call with (dict "root" . "component" "backend"). */}}
{{- define "campusslot.selectorLabels" -}}
app.kubernetes.io/name: {{ include "campusslot.name" .root }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/* Image references. The tag is mandatory so "latest" can never be deployed by accident. */}}
{{- define "campusslot.backendImage" -}}
{{- printf "%s:%s" .Values.backend.image.repository (required "backend.image.tag is required: pass the commit SHA with --set backend.image.tag=<sha>" .Values.backend.image.tag) -}}
{{- end -}}

{{- define "campusslot.frontendImage" -}}
{{- printf "%s:%s" .Values.frontend.image.repository (required "frontend.image.tag is required: pass the commit SHA with --set frontend.image.tag=<sha>" .Values.frontend.image.tag) -}}
{{- end -}}

{{/* Name of the Secret that holds DATABASE_URL. */}}
{{- define "campusslot.databaseSecretName" -}}
{{- default (printf "%s-database" (include "campusslot.fullname" .)) .Values.database.existingSecret -}}
{{- end -}}

{{/* Hardened container defaults: no privilege escalation, no capabilities, read-only filesystem. */}}
{{- define "campusslot.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
runAsNonRoot: true
capabilities:
  drop:
    - ALL
{{- end -}}
