terraform {
  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 2.19"
    }
  }
}

provider "docker" {
  # Use the local Docker daemon via the unix socket
  host = "unix:///var/run/docker.sock"
}

variable "image" {
  type    = string
  default = "nginx:stable-alpine"
}

variable "name" {
  type    = string
  default = "basic-nginx"
}

variable "host_port" {
  type    = number
  default = 8080
}

resource "docker_image" "nginx" {
  name = var.image
}

resource "docker_container" "nginx" {
  name  = var.name
  image = docker_image.nginx.latest

  ports {
    internal = 80
    external = var.host_port
  }

  restart = "unless-stopped"
}

output "container_id" {
  value = docker_container.nginx.id
}

output "host_port" {
  value = var.host_port
}
