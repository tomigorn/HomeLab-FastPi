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

variable "create_beefy_agent" {
  type    = bool
  default = true
}

variable "beefy_agent_host" {
  type    = string
  default = "beefy.local"
}

variable "beefy_agent_name" {
  type    = string
  default = "beefy"
}

variable "beefy_agent_port" {
  type    = number
  default = 9001
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

resource "null_resource" "create_beefy_agent" {
  triggers = {
    create = tostring(var.create_beefy_agent)
  }
  depends_on = [null_resource.bootstrap_portainer]

  provisioner "local-exec" {
    when    = create
    command = "bash ${path.module}/create_agent_endpoint.sh ${var.beefy_agent_host} ${var.beefy_agent_name} '${var.bootstrap_admin_password}' ${var.create_beefy_agent} ${var.beefy_agent_port}"
    interpreter = ["/bin/bash", "-c"]
  }
}
