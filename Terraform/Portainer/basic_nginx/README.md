Basic nginx Docker example (OpenTofu)

Run:

```bash
cd ~/Projects/Terraform/Portainer/basic_nginx
tofu init
tofu apply -auto-approve
curl -sS http://localhost:8080 | head -n 5
```
