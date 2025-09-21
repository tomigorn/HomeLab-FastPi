terraform {
  required_providers {
    local = {
      source  = "hashicorp/local"
      version = "~> 2.2"
    }
  }
}

provider "local" {}

variable "message" {
  type    = string
  default = "Hello from OpenTofu on FastPi!"
}

variable "filename" {
  type    = string
  default = "hello.txt"
}

resource "local_file" "hello" {
  content  = var.message
  filename = join("/", [path.module, var.filename])
}

output "file_path" {
  value = local_file.hello.filename
}
