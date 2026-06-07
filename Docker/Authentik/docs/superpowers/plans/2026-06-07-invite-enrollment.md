# Invite-Based Enrollment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Operators invite people via single-use, expiring links; signup forces a local account with mandatory MFA (TOTP or passkey), creates the user groupless, and the operator assigns groups manually. Also rename group `admin` → `super-admin`.

**Architecture:** Pure Authentik config-as-code. All objects declared in blueprints under `/home/pi/Projects/Docker/Authentik/blueprints/` and applied by the worker. Verification is via the Authentik REST API (Bearer token from `.env`), not unit tests. `[AGENT]` steps the assistant runs on the Pi; `[USER]` steps require a browser/human.

**Tech Stack:** Authentik 2026.5.2 blueprints (YAML), docker compose, REST API via curl.

---

## Conventions used by every task

- Run API checks from the project dir:
  ```bash
  cd /home/pi/Projects/Docker/Authentik
  TOKEN=$(grep '^AUTHENTIK_BOOTSTRAP_TOKEN=' .env | cut -d= -f2)
  api(){ docker compose exec -T server curl -s -H "Authorization: Bearer $TOKEN" "$@"; }
  ```
- Apply a blueprint immediately: `docker compose exec -T worker ak apply_blueprint /blueprints/custom/<file>.yaml`
  (the host `blueprints/` dir is mounted at `/blueprints/custom/` in the container).
- The CLI `apply_blueprint` can crash on its log serializer when an entry is invalid; if so,
  read the blueprint instance status via API instead:
  `api "http://localhost:9000/api/v3/managed/blueprints/" | python3 -m json.tool` and look at `status`.

---

## Task 1: Rename group `admin` → `super-admin`

**Files:**
- Modify: `blueprints/mvp.yaml` (group entry, ABS scope mapping, access bindings)

- [ ] **Step 1 [AGENT]: Edit the group entry** in `blueprints/mvp.yaml` — change both `name:` occurrences under the `group-admin` entry from `admin` to `super-admin` (leave the blueprint `id: group-admin` key as-is to minimize churn):

```yaml
  - model: authentik_core.group
    id: group-admin
    identifiers:
      name: super-admin
    attrs:
      name: super-admin
```

- [ ] **Step 2 [AGENT]: Update the ABS scope mapping** group check in `blueprints/mvp.yaml` (the `abs-groups` entry's expression):

```yaml
      expression: |
        if ak_is_group_member(user, name="super-admin"):
            return {"groups": ["admin"]}
        return {"groups": ["user"]}
```
(The emitted claim stays `["admin"]` so ABS config is unaffected; only the membership check changes.)

- [ ] **Step 3 [AGENT]: Apply and verify the renamed group exists**

```bash
docker compose exec -T worker ak apply_blueprint /blueprints/custom/mvp.yaml >/dev/null 2>&1
api "http://localhost:9000/api/v3/core/groups/?name=super-admin" | python3 -c "import sys,json;print('super-admin count:',json.load(sys.stdin)['pagination']['count'])"
```
Expected: `super-admin count: 1`

- [ ] **Step 4 [AGENT]: Delete the orphaned empty `admin` group** (blueprint match-by-name created a new group; the old one is now stale and empty)

```bash
PK=$(api "http://localhost:9000/api/v3/core/groups/?name=admin" | python3 -c "import sys,json;r=json.load(sys.stdin)['results'];print(r[0]['pk'] if r else '')")
[ -n "$PK" ] && api -X DELETE "http://localhost:9000/api/v3/core/groups/$PK/" -o /dev/null -w "delete admin group -> HTTP %{http_code}\n" || echo "no stale admin group"
api "http://localhost:9000/api/v3/core/groups/?name=admin" | python3 -c "import sys,json;print('leftover admin count:',json.load(sys.stdin)['pagination']['count'],'(want 0)')"
```
Expected: `HTTP 204` then `leftover admin count: 0`

- [ ] **Step 5 [AGENT]: Verify access bindings still resolve** (the bindings reference the group via `!KeyOf group-admin`, which now points at super-admin)

```bash
api "http://localhost:9000/api/v3/policies/bindings/" | python3 -c "
import sys,json
for b in json.load(sys.stdin)['results']:
    g=b.get('group_obj')
    if g: print('binding group:',g['name'],'-> target',b.get('target'))
"
```
Expected: bindings show group `super-admin` (Portainer ×1, ABS ×1) and `streaming` (ABS ×1).

- [ ] **Step 6 [AGENT]: Commit**

```bash
cd /home/pi/Projects && git add Docker/Authentik/blueprints/mvp.yaml
git commit -m "Authentik: rename admin group to super-admin"
```

---

## Task 2: Create the enrollment blueprint (stages + prompts)

**Files:**
- Create: `blueprints/enrollment.yaml`

- [ ] **Step 1 [AGENT]: Create `blueprints/enrollment.yaml`** with the prompt fields and all stages:

```yaml
version: 1
metadata:
  name: "Invite enrollment (local accounts + mandatory MFA)"
  labels:
    blueprints.goauthentik.io/instantiate: "true"
entries:
  # ---- Prompt fields ----
  - model: authentik_stages_prompt.prompt
    id: prompt-username
    identifiers: {field_key: username}
    attrs: {field_key: username, label: Username, type: username, required: true, order: 0, placeholder: Username}
  - model: authentik_stages_prompt.prompt
    id: prompt-email
    identifiers: {field_key: email}
    attrs: {field_key: email, label: Email, type: email, required: true, order: 1, placeholder: Email}
  - model: authentik_stages_prompt.prompt
    id: prompt-name
    identifiers: {field_key: name}
    attrs: {field_key: name, label: Display name, type: text, required: true, order: 2, placeholder: Name}
  - model: authentik_stages_prompt.prompt
    id: prompt-password
    identifiers: {field_key: password}
    attrs: {field_key: password, label: Password, type: password, required: true, order: 3, placeholder: Password}
  - model: authentik_stages_prompt.prompt
    id: prompt-password-repeat
    identifiers: {field_key: password_repeat}
    attrs: {field_key: password_repeat, label: Confirm password, type: password, required: true, order: 4, placeholder: Confirm password}

  # ---- Stages ----
  - model: authentik_stages_invitation.invitationstage
    id: stage-invitation
    identifiers: {name: enroll-invitation}
    attrs: {name: enroll-invitation, continue_flow_without_invitation: false}

  - model: authentik_stages_prompt.promptstage
    id: stage-prompt
    identifiers: {name: enroll-prompt}
    attrs:
      name: enroll-prompt
      fields:
        - !KeyOf prompt-username
        - !KeyOf prompt-email
        - !KeyOf prompt-name
        - !KeyOf prompt-password
        - !KeyOf prompt-password-repeat

  - model: authentik_stages_user_write.userwritestage
    id: stage-user-write
    identifiers: {name: enroll-user-write}
    attrs:
      name: enroll-user-write
      user_creation_mode: always_create
      user_type: internal
      # No create_users_group -> users are created groupless (assigned manually later).

  - model: authentik_stages_authenticator_totp.authenticatortotpstage
    id: stage-totp
    identifiers: {name: enroll-totp-setup}
    attrs: {name: enroll-totp-setup, friendly_name: Authenticator app (TOTP), digits: 6}

  - model: authentik_stages_authenticator_webauthn.authenticatorwebauthnstage
    id: stage-webauthn
    identifiers: {name: enroll-webauthn-setup}
    attrs: {name: enroll-webauthn-setup, friendly_name: Passkey / security key}

  - model: authentik_stages_authenticator_validate.authenticatorvalidatestage
    id: stage-mfa
    identifiers: {name: enroll-mfa-validate}
    attrs:
      name: enroll-mfa-validate
      not_configured_action: configure
      device_classes: [totp, webauthn]
      configuration_stages:
        - !KeyOf stage-totp
        - !KeyOf stage-webauthn

  - model: authentik_stages_user_login.userloginstage
    id: stage-login
    identifiers: {name: enroll-login}
    attrs: {name: enroll-login}
```

- [ ] **Step 2 [AGENT]: Apply and verify all stages exist**

```bash
docker compose exec -T worker ak apply_blueprint /blueprints/custom/enrollment.yaml 2>&1 | tail -3
for s in invitation prompt user_write authenticator_totp authenticator_webauthn authenticator_validate user_login; do :; done
api "http://localhost:9000/api/v3/stages/all/?search=enroll-" | python3 -c "import sys,json; d=json.load(sys.stdin); print('enroll stages:', sorted(x['name'] for x in d['results']))"
```
Expected: a list containing `enroll-invitation, enroll-prompt, enroll-user-write, enroll-totp-setup, enroll-webauthn-setup, enroll-mfa-validate, enroll-login`.

If apply errored: read `api "http://localhost:9000/api/v3/managed/blueprints/"` status and fix the offending entry's model/attrs, then re-apply.

---

## Task 3: Create the enrollment flow + stage bindings

**Files:**
- Modify: `blueprints/enrollment.yaml` (append flow + bindings)

- [ ] **Step 1 [AGENT]: Append the flow and ordered stage bindings** to `blueprints/enrollment.yaml`:

```yaml
  # ---- Enrollment flow ----
  - model: authentik_flows.flow
    id: flow-enroll
    identifiers: {slug: enroll}
    attrs:
      name: Account enrollment
      slug: enroll
      title: Create your account
      designation: enrollment
      authentication: require_unauthenticated

  # ---- Stage bindings (order defines flow sequence) ----
  - model: authentik_flows.flowstagebinding
    identifiers: {target: !KeyOf flow-enroll, stage: !KeyOf stage-invitation, order: 10}
    attrs: {evaluate_on_plan: true, re_evaluate_policies: false}
  - model: authentik_flows.flowstagebinding
    identifiers: {target: !KeyOf flow-enroll, stage: !KeyOf stage-prompt, order: 20}
    attrs: {evaluate_on_plan: true, re_evaluate_policies: false}
  - model: authentik_flows.flowstagebinding
    identifiers: {target: !KeyOf flow-enroll, stage: !KeyOf stage-user-write, order: 30}
    attrs: {evaluate_on_plan: true, re_evaluate_policies: false}
  - model: authentik_flows.flowstagebinding
    identifiers: {target: !KeyOf flow-enroll, stage: !KeyOf stage-mfa, order: 40}
    attrs: {evaluate_on_plan: true, re_evaluate_policies: false}
  - model: authentik_flows.flowstagebinding
    identifiers: {target: !KeyOf flow-enroll, stage: !KeyOf stage-login, order: 50}
    attrs: {evaluate_on_plan: true, re_evaluate_policies: false}
```

- [ ] **Step 2 [AGENT]: Apply and verify the flow + binding order**

```bash
docker compose exec -T worker ak apply_blueprint /blueprints/custom/enrollment.yaml 2>&1 | tail -3
FPK=$(api "http://localhost:9000/api/v3/flows/instances/enroll/" | python3 -c "import sys,json;print(json.load(sys.stdin)['pk'])")
api "http://localhost:9000/api/v3/flows/bindings/?target=$FPK" | python3 -c "
import sys,json
for b in sorted(json.load(sys.stdin)['results'], key=lambda x:x['order']):
    print(f\"  {b['order']:>3}  {b['stage_obj']['name']}\")
"
```
Expected, in order: `10 enroll-invitation, 20 enroll-prompt, 30 enroll-user-write, 40 enroll-mfa-validate, 50 enroll-login`.

- [ ] **Step 3 [AGENT]: Commit**

```bash
cd /home/pi/Projects && git add Docker/Authentik/blueprints/enrollment.yaml
git commit -m "Authentik: add invite enrollment flow with mandatory MFA"
```

---

## Task 4: Create a test invitation and run the end-to-end signup

**Files:** none (runtime objects + manual test)

- [ ] **Step 1 [AGENT]: Create a single-use, 1-day test invitation against the enroll flow**

```bash
FPK=$(api "http://localhost:9000/api/v3/flows/instances/enroll/" | python3 -c "import sys,json;print(json.load(sys.stdin)['pk'])")
# expiry ~24h from now, computed without Date in-shell:
EXP=$(docker compose exec -T server python3 -c "from datetime import datetime,timedelta,timezone;print((datetime.now(timezone.utc)+timedelta(days=1)).isoformat())")
api -X POST -H "Content-Type: application/json" \
  -d "{\"flow\":\"$FPK\",\"single_use\":true,\"expires\":\"$EXP\",\"fixed_data\":{}}" \
  "http://localhost:9000/api/v3/stages/invitation/invitations/" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print('invite token:',d['pk']);print('LINK: https://sso.holy-grail.ch/if/flow/enroll/?itoken='+d['pk'])"
```
Expected: prints a token and a full invite LINK.

- [ ] **Step 2 [USER]: Open the LINK in a private/incognito window** (logged out). Confirm:
  - You are taken straight into the enrollment flow (not asked to log in).
  - You can set username / email / name / password.
  - You are **forced** to set up MFA, and offered a choice of **TOTP** or **passkey**.
  - After MFA, you end up logged in as the new user.

- [ ] **Step 3 [USER → report]: Tell the assistant the new username.** Then **[AGENT]** verify the account exists and is groupless:

```bash
U=<username-the-user-reported>
api "http://localhost:9000/api/v3/core/users/?username=$U" | python3 -c "
import sys,json
u=json.load(sys.stdin)['results'][0]
print('user:',u['username'],'| groups:',u['groups_obj'] and [g['name'] for g in u['groups_obj']] or 'NONE (correct)')
"
```
Expected: `groups: NONE (correct)`.

- [ ] **Step 4 [AGENT]: Verify the invite is now consumed (single-use) — opening the same link again must fail.** Confirm the invitation is gone:

```bash
api "http://localhost:9000/api/v3/stages/invitation/invitations/" | python3 -c "import sys,json;print('remaining invites:',json.load(sys.stdin)['pagination']['count'])"
```
Expected: `0` (the single-use invite was consumed). **[USER]** optionally re-open the old link → expect "invitation invalid/expired".

- [ ] **Step 5 [USER]: In the admin UI, assign the test user to a group** — Directory → Groups → `streaming` → Users → Add existing user → pick the test user → Add. Confirm via **[AGENT]**:

```bash
U=<username>
api "http://localhost:9000/api/v3/core/users/?username=$U" | python3 -c "import sys,json;print('groups now:',[g['name'] for g in json.load(sys.stdin)['results'][0]['groups_obj']])"
```
Expected: `['streaming']`.

---

## Task 5: Document + finalize

**Files:**
- Modify: `Docker/Authentik/README.md` (add an "Inviting users" section)
- Modify: memory `authentik-sso-project.md`

- [ ] **Step 1 [AGENT]: Add an "Inviting users" section to `Docker/Authentik/README.md`** describing: invites are single-use + expiring, created in Directory → Invitations against the `enroll` flow (or the API one-liner from Task 4), the link format `https://sso.holy-grail.ch/if/flow/enroll/?itoken=<token>`, that signup forces MFA, and that **groups are assigned manually after signup**.

- [ ] **Step 2 [AGENT]: Update the project memory** (`authentik-sso-project.md`) to record: group renamed to `super-admin`; `enroll` flow live (invitation-gated, mandatory TOTP/passkey, groupless signup, manual group assignment); Google sign-up still deferred.

- [ ] **Step 3 [AGENT]: Commit**

```bash
cd /home/pi/Projects && git add Docker/Authentik/README.md
git commit -m "Authentik: document invite-based user enrollment"
```

---

## Self-review notes (author)

- **Spec coverage:** rename (Task 1), invitation-gated flow (Task 3 step 1, invitation stage), local prompt fields (Task 2), mandatory MFA TOTP/passkey (Task 2 stage-mfa + Task 3 binding), single-use + expiry invites (Task 4), groupless + manual assignment (Task 2 user-write, Task 4 steps 3/5) — all covered.
- **Deferred correctly:** Google sign-up not in any task (out of scope).
- **Risk:** exact attr names for stages in Authentik 2026.5 may need a tweak on first apply; Task 2/3 verify steps catch this and the convention note explains how to read the real error.
