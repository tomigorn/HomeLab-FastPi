# Secrets for Portainer deployment
# Put values here and DO NOT commit this file. This file is gitignored by `Portainer/.gitignore`.
# Example usage:
#   tofu apply -var-file=secrets.tfvars

# Admin password for Portainer initial bootstrap (required to run the bootstrap script)
bootstrap_admin_password = "This is your Password123! ChangeMeNow!"

# Example placeholders for future secrets you may want to store here:
# registry_username = "your-registry-username"
# registry_password = "your-registry-password"