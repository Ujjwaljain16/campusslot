{{/*
The backend pod template. The Deployment and the Argo Rollout both use it, so a canary release runs
exactly the same pod as a normal rolling update. Call it with the root context: include "campusslot.backendPodTemplate" .
*/}}
{{- define "campusslot.backendPodTemplate" -}}
metadata:
  labels:
    {{- include "campusslot.selectorLabels" (dict "root" . "component" "backend") | nindent 4 }}
  annotations:
    # A changed database Secret rolls the pods so they pick up the new connection string.
    checksum/database-secret: {{ include (print $.Template.BasePath "/secret.yaml") . | sha256sum }}
    # A changed ConfigMap rolls the pods too, because environment variables are read only at start.
    checksum/backend-config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
spec:
  serviceAccountName: {{ include "campusslot.fullname" . }}
  automountServiceAccountToken: false
  {{- with .Values.imagePullSecrets }}
  imagePullSecrets:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  securityContext:
    runAsNonRoot: true
    runAsUser: 10001
    runAsGroup: 10001
    seccompProfile:
      type: RuntimeDefault
  terminationGracePeriodSeconds: 30
  containers:
    - name: backend
      image: {{ include "campusslot.backendImage" . | quote }}
      imagePullPolicy: {{ .Values.backend.image.pullPolicy }}
      ports:
        - name: http
          containerPort: {{ .Values.backend.port }}
      envFrom:
        - configMapRef:
            name: {{ include "campusslot.fullname" . }}-backend-config
      env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: {{ include "campusslot.databaseSecretName" . }}
              key: {{ .Values.database.secretKey }}
      # Starting up: give the app up to a minute before liveness checks can restart it.
      startupProbe:
        httpGet: { path: /health, port: http }
        periodSeconds: 2
        failureThreshold: 30
      # Readiness: only receive traffic when the database is reachable and migrated.
      # Keep serving for a few seconds after the pod is marked for deletion. The ingress controller
      # learns about the removal a moment later, and until then it still sends requests here.
      {{- with .Values.preStopDelaySeconds }}
      lifecycle:
        preStop:
          exec:
            command: ["sleep", {{ . | quote }}]
      {{- end }}
      readinessProbe:
        httpGet: { path: /ready, port: http }
        periodSeconds: 5
        timeoutSeconds: 3
        failureThreshold: 3
      # Liveness: independent of the database, so a database outage never restarts the pods.
      livenessProbe:
        httpGet: { path: /health, port: http }
        periodSeconds: 15
        timeoutSeconds: 3
        failureThreshold: 3
      resources:
        {{- toYaml .Values.backend.resources | nindent 8 }}
      securityContext:
        {{- include "campusslot.containerSecurityContext" . | nindent 8 }}
      volumeMounts:
        - name: tmp
          mountPath: /tmp
  volumes:
    - name: tmp
      emptyDir: {}
{{- end }}
