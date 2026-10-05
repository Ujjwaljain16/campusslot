.PHONY: test lint up down deploy-local port-forward load-test clean

# Backend tests on the fast SQLite database
test:
	cd backend && pytest -v

lint:
	cd backend && ruff check . && ruff format --check . && bandit -r app -ll

# Local stack with Docker Compose
up:
	docker compose up --build -d

down:
	docker compose down

# Deploy the images that CI built for a commit to the Minikube cluster:  make deploy-local SHA=<commit>
deploy-local:
	@test -n "$(SHA)" || (echo "usage: make deploy-local SHA=<commit-sha>"; exit 1)
	./scripts/deploy-local.sh $(SHA)

# Reach the application through the ingress controller at http://localhost:8080
port-forward:
	kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8080:80

# Generate traffic so the HPA has something to react to
load-test:
	./scripts/load-test.sh

clean:
	helm uninstall campusslot -n campusslot || true
	kubectl delete pvc --all -n campusslot || true
