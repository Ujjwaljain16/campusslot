#!/usr/bin/env bash
# Start a throw-away S3 compatible object store on the laptop cluster, with random credentials, and create the
# bucket that the database backups use.
#
#   scripts/install-objectstore.sh
#
# The credentials are generated here, stored only as Secrets in the cluster (one in the object-store namespace
# for the server, one in the application namespace for the backup plugin), and never written to a file.
# k8s/objectstore.yaml explains why this is a laptop stand-in and not part of the application chart.
set -euo pipefail

NAMESPACE="${NAMESPACE:-campusslot}"
BUCKET="${BUCKET:-campusslot-backups}"
OBJECTSTORE_IMAGE="${OBJECTSTORE_IMAGE:-rustfs/rustfs:1.0.3}"   # the tag that the phase 3 drill ran with
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

kubectl create namespace object-store --dry-run=client -o yaml | kubectl apply -f - >/dev/null

if kubectl get secret object-store-credentials -n object-store >/dev/null 2>&1; then
  ACCESS_KEY="$(kubectl get secret object-store-credentials -n object-store -o jsonpath='{.data.ACCESS_KEY_ID}' | base64 -d)"
  SECRET_KEY="$(kubectl get secret object-store-credentials -n object-store -o jsonpath='{.data.ACCESS_SECRET_KEY}' | base64 -d)"
  echo "Reusing the credentials of the running object store"
else
  ACCESS_KEY="$(openssl rand -hex 8)"
  SECRET_KEY="$(openssl rand -hex 16)"
fi

kubectl create secret generic object-store-credentials -n object-store \
  --from-literal=ACCESS_KEY_ID="$ACCESS_KEY" --from-literal=ACCESS_SECRET_KEY="$SECRET_KEY" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl create secret generic object-store-credentials -n "$NAMESPACE" \
  --from-literal=ACCESS_KEY_ID="$ACCESS_KEY" --from-literal=ACCESS_SECRET_KEY="$SECRET_KEY" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

# The manifest names the image through a variable, so that the tag is chosen here and not edited in the file.
sed "s#\${OBJECTSTORE_IMAGE}#${OBJECTSTORE_IMAGE}#" "$ROOT/k8s/objectstore.yaml" | kubectl apply -f -
kubectl rollout status deployment/rustfs -n object-store --timeout=180s

# Create the bucket with a one-off pod that uses the S3 API. The AWS CLI image is only used for this step.
kubectl delete pod create-bucket -n object-store --ignore-not-found >/dev/null
kubectl run create-bucket -n object-store --restart=Never --rm -i --quiet \
  --image=amazon/aws-cli:2.17.0 \
  --env="AWS_ACCESS_KEY_ID=$ACCESS_KEY" --env="AWS_SECRET_ACCESS_KEY=$SECRET_KEY" --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- sh -c "aws --endpoint-url http://rustfs:9000 s3 mb s3://${BUCKET} || aws --endpoint-url http://rustfs:9000 s3 ls s3://${BUCKET}"

echo "object store ready: http://rustfs.object-store.svc:9000, bucket ${BUCKET}"
