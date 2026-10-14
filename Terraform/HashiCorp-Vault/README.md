# OpenTofu (Terraform) — Vault Docker deployment

This small OpenTofu (Terraform-compatible) project creates a Docker container running HashiCorp Vault in *dev mode* with a deterministic root token. This mirrors your working docker-compose setup and is intended for local labs only.

Files created
- `provider.tf` — Docker provider configuration (uses `/var/run/docker.sock`).
- `main.tf` — Docker image, volume, network, and container resources.
- `variables.tf` — Variable defaults (image, token, container name, address).
- `outputs.tf` — Helpful outputs after apply.
- `.gitignore` — ignore state files.

Quick start

1. Ensure OpenTofu (`tofu`) is installed and you have Docker running locally.

```bash
cd /home/pi/Projects/Terraform/HashiCorp-Vault
tofu init
tofu apply -auto-approve
```

2. Check container:

```bash
docker ps --filter name=${var.container_name:-vault}
```

3. Access Vault UI or API at `http://<host-ip>:8200`.

Notes and security
- This configuration runs Vault in `dev` mode (via `VAULT_DEV_ROOT_TOKEN_ID`) which is insecure and should only be used for local testing. Dev mode enables a single unsealed instance and stores secrets in-memory.
- If you want a production-like setup, modify `main.tf` to run Vault server mode with a real backend (Consul/S3/etc.), enable TLS and configure auto-unseal.

Customizations
- To change the dev token, set the `dev_root_token` variable (e.g., via `-var 'dev_root_token=mytoken'`).
- To use a specific Vault image tag, set `vault_image` variable.

Next steps for production
- Replace dev-mode env var with real `vault.hcl` file mount and server command.
- Add auto-unseal (KMS) or integrated storage like Consul.
- Configure TLS certificates and `api_addr`.
