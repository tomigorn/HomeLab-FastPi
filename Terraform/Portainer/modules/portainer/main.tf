terraform {
  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 2.19"
    }
  }
}

provider "docker" {
  host = var.docker_host
}

resource "docker_volume" "data" {
  name = var.data_volume_name
}

resource "docker_image" "portainer" {
  name = var.image
}

resource "docker_container" "portainer" {
  name  = var.container_name
  image = docker_image.portainer.name

  restart = var.restart_policy

  dynamic "volumes" {
    for_each = var.extra_volumes
    content {
      host_path      = split(":", volumes.value)[0]
      container_path = split(":", volumes.value)[1]
    }
  }

  volumes {
    volume_name    = docker_volume.data.name
    container_path = "/data"
  }

  ports {
    internal = 9000
    external = var.portainer_port
  }

  env = var.env
}
