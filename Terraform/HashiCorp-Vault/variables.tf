variable "project_name" {
  type    = string
  default = "vault"
}

variable "container_name" {
  type    = string
  default = "vault"
}

variable "network_name" {
  type    = string
  default = "vault_network"
}

variable "vault_image" {
  type    = string
  default = "hashicorp/vault:latest"
}

variable "dev_root_token" {
  type    = string
  default = "myroot"
  description = "Dev-mode root token id. Only used because container runs in dev mode."
}

variable "vault_addr" {
  type    = string
  default = "http://127.0.0.1:8200"
  description = "Address advertised for Vault. Override if you want a specific host IP."
}
