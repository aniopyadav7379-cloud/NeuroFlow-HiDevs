.PHONY: security-scan build-api build-frontend

API_IMAGE := neuroflow-api:latest
FRONTEND_IMAGE := neuroflow-frontend:latest

build-api:
	docker build -f backend/Dockerfile -t $(API_IMAGE) .

build-frontend:
	docker build -f frontend/Dockerfile -t $(FRONTEND_IMAGE) frontend

# Scans the built image for known vulnerabilities and fails the build on
# any CRITICAL finding. Requires the api image to already be built (via
# `make build-api`) — this target does not build it itself, so CI can
# cache/build once and scan the same artifact it's about to ship.
security-scan:
	@command -v trivy >/dev/null 2>&1 || { echo "trivy not installed — see https://aquasecurity.github.io/trivy/latest/getting-started/installation/"; exit 1; }
	trivy image --severity CRITICAL --exit-code 1 --ignore-unfixed $(API_IMAGE)
	trivy image --severity CRITICAL --exit-code 1 --ignore-unfixed $(FRONTEND_IMAGE)
