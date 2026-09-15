.PHONY: security-scan

IMAGE_NAME ?= neuroflow-api:latest

security-scan:
	@echo "Scanning image $(IMAGE_NAME) for CRITICAL vulnerabilities in application libraries..."
	trivy image --vuln-type library --severity CRITICAL --exit-code 1 $(IMAGE_NAME)
