output "container_id" {
  value = docker_container.vault.id
}

output "container_name" {
  value = docker_container.vault.name
}

output "vault_address" {
  value = var.vault_addr
}
