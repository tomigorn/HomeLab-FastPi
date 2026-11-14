# Lost authenticator or password

## Lost password

Your friend can do it alone: **Forgot password?** on the login page. They get an email link and must also type a code from their authenticator app.

## Lost authenticator (phone lost or new phone)

Without the authenticator the person cannot log in. Make a one-time login link on the server:

```bash
cd ~/Projects/Docker/Authentik
docker compose exec -T server ak create_recovery_key 60 <username>
```

`60` is how many minutes the link works. Send the link to the person only.

1. The person opens the link and sets a new password.
2. They set up a new authenticator when asked.
