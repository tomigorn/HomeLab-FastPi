# Security follow-ups (from Phase A review — non-blocking)

The critical finding (2FA bypass via the standard password endpoint) was FIXED in Phase A
(`guards.go`, with regression test `TestStandardPasswordEndpointBlocksTotpUser`). Non-root
container and auth rate limiting were also fixed. These remaining items are hardening to weigh
during Phases B/C or a later pass:

- **I2 — `/required` user-enumeration oracle.** `POST /api/loyalty/totp/required` reveals whether
  an identity exists with 2FA on. Already collapses "no user" and "no TOTP" to `false`; now also
  rate-limited (6/60s). Accept, or require password before revealing 2FA status.
- **I4 — No step-up auth on `/setup`/`/enable`/`/disable`.** A holder of a (long-lived) token can
  start TOTP re-enrollment. `/enable` still needs a code from the new secret and `/disable` needs a
  current code, so impact is limited. Consider requiring the account password for these.
- **I5 — ~3-year auth tokens (by design).** Meets the user's "never log out" requirement, but a
  stolen token is a long-lived foothold with no per-session revocation (only rotating the collection
  token secret, which logs everyone out). Document an admin "invalidate all sessions" procedure;
  optionally move to shorter token + silent refresh later.
- **M1 — Open signup default.** Decide in the admin UI at deploy (see DEPLOY.md). Optionally set
  `users.CreateRule` in the migration so a fresh deploy is locked-down by default.
- **M3 — Admin console `/_/` publicly reachable.** Treat the Traefik IP-allowlist / basic-auth in
  front of `/_/` as recommended, given it's a brute-force target.
- **M4 — Add length/charset checks** on `code`/`identity` in the custom routes (cheap hardening).

Done well (for the record): owner isolation is correct and tested (all 5 CRUD rules, no owner
spoofing on create); TOTP secrets are `Hidden:true`; pending-vs-active secret separation is sound;
TOTP window is standard; multi-stage non-root build; no host ports; secure-headers middleware.
