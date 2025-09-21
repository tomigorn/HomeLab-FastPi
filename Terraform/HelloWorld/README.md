HelloWorld OpenTofu project

This small example writes a file `hello.txt` next to the configuration with a
greeting message using the `local_file` resource.

Quick start:

```bash
cd ~/Projects/Terraform/HelloWorld
tofu init
tofu plan
tofu apply -auto-approve
cat hello.txt
```

Cleanup:

```bash
tofu destroy -auto-approve
```
