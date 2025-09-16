variable "auth_postgres_password" {
  type      = string
  sensitive = true
  description = "Postgres password for authentik DB (override via -var-file or env)"
}

variable "auth_secret_key" {
  type      = string
  sensitive = true
  description = "AUTHENTIK_SECRET_KEY (do not hardcode)"
}

variable "redis_password" {
  type      = string
  sensitive = true
  description = "Password for Redis (requirepass)"
}