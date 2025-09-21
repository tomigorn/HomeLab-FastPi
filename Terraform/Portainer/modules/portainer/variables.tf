variable "docker_host" {
  description = "Docker host connection string (unix socket). Example: unix:///var/run/docker.sock"
  type        = string
  default     = "unix:///var/run/docker.sock"
}

variable "image" {
  type    = string
  default = "portainer/portainer-ce:latest"
}

variable "container_name" {
  type    = string
  default = "portainer"
}

variable "data_volume_name" {
  type    = string
  default = "portainer_data"
}

variable "portainer_port" {
  type    = number
  default = 9443
}

variable "restart_policy" {
  type    = string
  default = "unless-stopped"
}

variable "extra_volumes" {
  type    = list(string)
  default = []
}

variable "env" {
  type    = list(string)
  default = []
}
