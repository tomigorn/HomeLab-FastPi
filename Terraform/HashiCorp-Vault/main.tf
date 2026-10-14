resource "docker_image" "vault" {
  name         = var.vault_image
  keep_locally = false
}

resource "docker_volume" "vault_data" {
  name = "${var.project_name}_vault_data"
}

resource "docker_network" "vault_network" {
  name = var.network_name
}

resource "docker_container" "vault" {
  name      = var.container_name
  image     = docker_image.vault.name
  restart   = "unless-stopped"

  networks_advanced {
    name = docker_network.vault_network.name
  }

  ports {
    internal = 8200
    external = 8200
  }

  env = [
    "VAULT_DEV_ROOT_TOKEN_ID=${var.dev_root_token}",
    "VAULT_ADDR=${var.vault_addr}",
  ]

  volumes {
    volume_name    = docker_volume.vault_data.name
    container_path = "/vault/file"
  }

  host_config {
    cap_add = ["IPC_LOCK"]
  }

  healthcheck {
    test     = ["CMD-SHELL", "vault status || exit 1"]
    interval = "30s"
    timeout  = "10s"
    retries  = 5
  }
}
