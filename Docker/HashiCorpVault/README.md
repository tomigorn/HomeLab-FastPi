# HashiCorp Vault (local docker-compose)

This directory contains a simple Docker Compose setup to run a local HashiCorp Vault server for lab/dev use.

Quick steps
- Start Vault:

```bash
cd /home/pi/Projects/Docker/HashiCorpVault
docker compose up -d
```

- Initialize and unseal (run on host):

```bash
./init_vault.sh
```

This saves `init.json`, `unseal_key.txt` and `root_token.txt` in `./secrets/` (the folder is gitignored). If you don't have `jq` installed, `init.json` will still be produced and you can extract the values manually.

- Login to Vault (example):

```bash
CONTAINER="${COMPOSE_PROJECT_NAME:-vault}_vault"
ROOT_TOKEN=$(cat ./secrets/root_token.txt)
docker exec -it $CONTAINER vault login $ROOT_TOKEN
```

- Enable kv v2 and test writing a secret:

```bash
docker exec -it $CONTAINER vault auth list || true
docker exec -it $CONTAINER sh -c 'vault secrets enable -path=secret kv-v2 || true'
docker exec -it $CONTAINER sh -c 'vault kv put secret/hello value=world'
docker exec -it $CONTAINER sh -c 'vault kv get -format=json secret/hello'
```

Notes & next steps
- This setup disables TLS for convenience. Do NOT expose this to untrusted networks.
- For production: enable TLS, use an auto-unseal mechanism (KMS), and a resilient storage backend (Consul, S3, etc.).
- See HashiCorp Vault docs for hardening and backup/restore procedures.
