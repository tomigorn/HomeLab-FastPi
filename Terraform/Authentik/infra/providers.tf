terraform {
  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
  required_version = ">= 1.0"
}

provider "docker" {
  host = "unix:///var/run/docker.sock"
}