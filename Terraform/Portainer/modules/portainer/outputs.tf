output "container_name" {
  value = docker_container.portainer.name
}

output "data_volume" {
  value = docker_volume.data.name
}
