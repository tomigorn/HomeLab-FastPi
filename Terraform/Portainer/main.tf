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
