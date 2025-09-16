## Makefile for Authentik OpenTofu/Terraform project
# TOOL can be set to 'tofu', 'openTofu', or 'terraform' depending on your installed binary

.PHONY: init plan apply destroy build-wakeproxy run-wakeproxy

TOOL ?= $(shell command -v tofu || command -v openTofu || command -v terraform || echo openTofu)

init:
	cd infra && $(TOOL) init

plan:
	# If infra/secrets.tfvars exists, pass it to the tool to avoid interactive prompts
	cd infra && if [ -f secrets.tfvars ]; then $(TOOL) plan -var-file=secrets.tfvars; else $(TOOL) plan; fi

apply:
	# Use var-file if present to avoid interactive prompts and ensure secrets are provided
	cd infra && if [ -f secrets.tfvars ]; then $(TOOL) apply -var-file=secrets.tfvars -auto-approve; else $(TOOL) apply -auto-approve; fi

destroy:
	cd infra && $(TOOL) destroy -auto-approve

# Build the wake-proxy docker image (tagged local)
build-wakeproxy:
	docker build -t authentik-wake-proxy:local ./scripts/wake_proxy

# Run wake-proxy locally for testing
run-wakeproxy:
	docker run --rm -p 8080:8080 --name wake-proxy -v $(PWD)/scripts/wake_proxy/config.yml:/app/config.yml authentik-wake-proxy:local
