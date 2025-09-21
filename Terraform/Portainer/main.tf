terraform {
  required_providers {
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
    }
  }
}

module "portainer" {
  source           = "./modules/portainer"
  docker_host      = "unix:///var/run/docker.sock"
  image            = "portainer/portainer-ce:latest"
  container_name   = "portainer"
  data_volume_name = "portainer_data"
  portainer_port   = 9443
  extra_volumes    = ["/var/run/docker.sock:/var/run/docker.sock"]
  env              = []
}

output "portainer_container" {
  value = module.portainer.container_name
}

output "portainer_data_volume" {
  value = module.portainer.data_volume
}

variable "bootstrap_admin_password" {
  type    = string
  default = ""
}

resource "null_resource" "bootstrap_portainer" {
  # only run when password provided
  triggers = {
    password     = var.bootstrap_admin_password
    container_id = module.portainer.container_id
  }
  depends_on = [module.portainer]

  provisioner "local-exec" {
    when    = create
    command = "bash ${path.module}/bootstrap_portainer_full.sh localhost 9000 '${var.bootstrap_admin_password}'"
    interpreter = ["/bin/bash", "-c"]
  }
}
