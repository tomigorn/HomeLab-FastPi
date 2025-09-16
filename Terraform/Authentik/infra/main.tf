resource "docker_volume" "auth_postgres" {
  name = "authentik_postgres"
}

resource "docker_network" "authnet" {
  name = "authentik_net"
}

resource "docker_container" "postgres" {
  name  = "auth_postgres"
  image = "postgres:15"
  env = [
    "POSTGRES_DB=authentik",
    "POSTGRES_USER=authentik",
    "POSTGRES_PASSWORD=${replace(var.auth_postgres_password, "\n", "") }"
  ]
  volumes {
    host_path      = "/home/pi/Projects/Terraform/Authentik/data/postgres"
    container_path = "/var/lib/postgresql/data"
  }
  networks_advanced {
    name = docker_network.authnet.name
  }
  restart = "unless-stopped"
}

resource "docker_volume" "auth_redis" {
  name = "authentik_redis"
}

resource "docker_container" "redis" {
  name  = "auth_redis"
  image = "redis:6"
  command = ["redis-server", "--requirepass", replace(var.redis_password, "\n", "")]
  volumes {
    host_path      = "/home/pi/Projects/Terraform/Authentik/data/redis"
    container_path = "/data"
  }
  networks_advanced {
    name = docker_network.authnet.name
  }
  restart = "unless-stopped"
}

resource "docker_container" "authentik" {
  name  = "authentik"
  image = "ghcr.io/goauthentik/server:latest"
  env = [
    # URL-encode '/' and '=' in passwords so they don't break the connection string parsing
  "DATABASE_URL=postgres://authentik:${replace(replace(replace(var.auth_postgres_password, "\n", ""), "/", "%2F"), "=", "%3D") }@auth_postgres:5432/authentik",
  "REDIS_URL=redis://:${replace(replace(replace(var.redis_password, "\n", ""), "/", "%2F"), "=", "%3D") }@auth_redis:6379/0",
  "AUTHENTIK_SECRET_KEY=${replace(var.auth_secret_key, "\n", "") }",

  # Also set explicit variables with AUTHENTIK_ prefix so the ConfigLoader maps them
  # into postgresql.* and redis.* (Authen tik expects AUTHENTIK_POSTGRESQL__HOST etc.)
  "AUTHENTIK_POSTGRESQL__HOST=auth_postgres",
  "AUTHENTIK_POSTGRESQL__PORT=5432",
  "AUTHENTIK_POSTGRESQL__NAME=authentik",
  "AUTHENTIK_POSTGRESQL__USER=authentik",
  "AUTHENTIK_POSTGRESQL__PASSWORD=${replace(var.auth_postgres_password, "\n", "")}",
  "AUTHENTIK_REDIS__HOST=auth_redis",
  "AUTHENTIK_REDIS__PORT=6379",
  "AUTHENTIK_REDIS__DB=0",
  "AUTHENTIK_REDIS__PASSWORD=${replace(var.redis_password, "\n", "")}",
  # Force Authentik to listen on TCP inside the container (bind to 0.0.0.0:9000)
  "AUTHENTIK_LISTEN__LISTEN_HTTP=0.0.0.0:9000",
  ]
  volumes {
    host_path      = "/home/pi/Projects/Terraform/Authentik/data/authentik_media"
    container_path = "/data"
  }
  ports {
    # Map container TCP 9000 -> host 9000 so docker-proxy and iptables DNAT target the correct container port
    internal = 9000
    external = 9000
  }
  command = ["server"]
  restart = "unless-stopped"
  networks_advanced {
    name = docker_network.authnet.name
  }
  depends_on = [
    docker_container.postgres,
    docker_container.redis
  ]
}
