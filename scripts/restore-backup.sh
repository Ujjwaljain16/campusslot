#!/usr/bin/env bash
# Restore the database from a backup written by the backup CronJob (helm value backup.enabled).
#
#   scripts/restore-backup.sh                                  # newest backup
#   scripts/restore-backup.sh campusslot-20261006T100000Z.dump # a specific one
#
# It starts a short-lived pod that mounts the backup volume read-only and runs pg_restore against
# the live database, then removes the pod. Existing tables are dropped and recreated in one
# transaction, so everything written after the backup is lost: at most one backup interval (the RPO).
# The procedure and a measured drill are in docs/engineering/backup-drill.md.
set -euo pipefail

NAMESPACE="${NAMESPACE:-campusslot}"
RELEASE="${RELEASE:-campusslot}"
FILE="${1:-}"
case "$RELEASE" in
  *campusslot*) NAME="$RELEASE" ;;
  *) NAME="${RELEASE}-campusslot" ;;
esac
POD="${NAME}-restore"

field() { kubectl get statefulset "${NAME}-postgres" -n "$NAMESPACE" -o jsonpath="$1"; }
IMAGE="$(field '{.spec.template.spec.containers[0].image}')"
DATABASE="$(field '{.spec.template.spec.containers[0].env[?(@.name=="POSTGRES_DB")].value}')"
DBUSER="$(field '{.spec.template.spec.containers[0].env[?(@.name=="POSTGRES_USER")].value}')"

kubectl delete pod "$POD" -n "$NAMESPACE" --ignore-not-found >/dev/null
kubectl apply -n "$NAMESPACE" -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: ${POD}
  labels:
    app.kubernetes.io/name: campusslot
    app.kubernetes.io/component: restore
spec:
  restartPolicy: Never
  automountServiceAccountToken: false
  securityContext:
    runAsNonRoot: true
    runAsUser: 70
    runAsGroup: 70
    fsGroup: 70
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: pg-restore
      image: ${IMAGE}
      command:
        - sh
        - -c
        - |
          set -eu
          file="/backups/${FILE}"
          [ -n "${FILE}" ] || file="\$(ls -1t /backups/*.dump | head -1)"
          echo "restoring \$file"
          pg_restore --clean --if-exists --no-owner --single-transaction --dbname="${DATABASE}" "\$file"
          echo "restore finished"
      env:
        - name: PGHOST
          value: ${NAME}-postgres
        - name: PGUSER
          value: ${DBUSER}
        - name: PGPASSWORD
          valueFrom:
            secretKeyRef:
              name: ${NAME}-database
              key: POSTGRES_PASSWORD
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: ["ALL"]
      volumeMounts:
        - name: backups
          mountPath: /backups
          readOnly: true
  volumes:
    - name: backups
      persistentVolumeClaim:
        claimName: ${NAME}-backups
EOF

if ! kubectl wait -n "$NAMESPACE" --for=jsonpath='{.status.phase}'=Succeeded "pod/$POD" --timeout=180s; then
  kubectl logs -n "$NAMESPACE" "$POD" || true
  kubectl delete pod "$POD" -n "$NAMESPACE" --wait=false >/dev/null
  exit 1
fi
kubectl logs -n "$NAMESPACE" "$POD"
kubectl delete pod "$POD" -n "$NAMESPACE" --wait=false >/dev/null
