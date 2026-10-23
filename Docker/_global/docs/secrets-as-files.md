# Secrets as files, not environment

Why: every reader of the Docker API (socket proxies, telegraf, cup-agent, Portainer, autoheal) sees each container's env via `docker inspect`. A file mounted into one container is readable only by that container's uid.

Same recipe on fastpi and beefy (beefy: `sudo docker …`).

## Rules

| Rule | How |
|---|---|
| Where | `<project>/secrets/<name>` (gitignored by `Docker/.gitignore`: `secrets/`, `*.secret`) |
| Owner / mode | uid (and gid) of the container that reads it, `0400`; shared by two uids → `owner:group` + `0440`; root containers → `root:root 0400`. Uids: `container-hardening.md` |
| Content | the bare value, no trailing newline (`printf %s`) |
| Mount | compose `secrets:` with `file:` (lands at `/run/secrets/<name>`, keeps host owner/mode) or a `:ro` bind |
| Read | the app's own file option (table below) |
| `.env` | non-secret config only; `.env.example` names the secret files |
| Check | `docker inspect <c> --format '{{range .Config.Env}}{{println .}}{{end}}' \| cut -d= -f1` shows no secret name with a value |

## Create a file from an existing `.env` value (never echoes it)

```bash
cd <project> && mkdir -p secrets
v=$(grep -E '^VAR=' .env | tail -1 | cut -d= -f2-); umask 077
printf %s "$v" > secrets/name; unset v
sudo chown <uid>:<gid> secrets/name && sudo chmod 0400 secrets/name
sed -i -E '/^VAR=/d' .env
```

Compose:

```yaml
services:
  app:
    environment:
      - VAR_FILE=/run/secrets/name
    secrets:
      - name
secrets:
  name:
    file: ./secrets/name
```

## Native file options (verified)

| App | Option |
|---|---|
| postgres image | `POSTGRES_PASSWORD_FILE` |
| Authentik | value `file:///run/secrets/<name>` for any `AUTHENTIK_*` (unreadable file = empty value, check `Failed to read config` in the log) |
| Grafana | `GF_<SECTION>_<KEY>__FILE`; provisioning files `$__file{/run/secrets/<name>}` |
| InfluxDB 2 image | `DOCKER_INFLUXDB_INIT_PASSWORD_FILE` (setup only) |
| Telegraf | `[[secretstores.docker]] id = "docker_secretstore"` + `@{docker_secretstore:<name>}` |
| Traefik (lego DNS) | `<VAR>_FILE`, e.g. `CF_DNS_API_TOKEN_FILE` |
| Traefik CrowdSec plugin | `crowdsecLapiKeyFile` |
| gluetun | `WIREGUARD_PRIVATE_KEY_SECRETFILE` (default `/run/secrets/wireguard_private_key`) |
| linuxserver images | `FILE__<VAR>=/run/secrets/<name>` |
| Mousehole | `MOUSEHOLE_AUTH_PASSWORD_FILE` |
| cloudflared | `--token-file` |
| pydantic-settings apps | dotenv file mounted at the app's `env_file` path (Stonks: `/app/.env`) |
| ASP.NET Core | `appsettings.<Environment>.json` mounted into the content root |

## No file option

Image has a shell: one-line compose entrypoint that exports the variable from the file, then `exec`s the original entrypoint (DDNS noip, mouse samba, WireguardVPN wg-easy). The value is then only in the process env, not in `docker inspect`.

No shell (Portainer `AGENT_SECRET`): stays in env, listed in the project README.
