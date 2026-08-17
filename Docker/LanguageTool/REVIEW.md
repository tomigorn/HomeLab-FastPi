# Step 1 — Critical review (and what the build then proved)

Written before implementing, updated with what testing confirmed. The
short version: the original setup was more mature than "rough" but was
**not actually running** (the container was stopped), and it had a latent
bug that would have crashed it. The plan was mostly right; five points
needed correcting.

## What already existed

`erikvl87/languagetool:6.7-dockerupdate-4`, no host port, behind Traefik
(basic-auth + secure-headers, Cloudflare cert) on `traefik_proxy`. A
clever custom entrypoint that appends spelling and merges custom grammar
into LT's built-ins at start. Working-looking Swiss rules, a de_CH
Helvetism spelling list, pipeline caching on. Dual Pi+Mac instances
sharing a git-synced `shared/` tree. **Keeping all of this** — it's the
right shape.

## Corrections made (each differs from the request for a reason)

1. **`level=picky` can't be server-side.** Verified in `HTTPServerConfig`
   and confirmed by the LT maintainer: picky is per-request only. → Set
   it per client (documented in `CLIENTS.md`), not on the server.

2. **Picky vs precision is a real tension.** Picky raises recall and
   *lowers* precision. Kept the "picky + curated `disabledRuleIds`"
   strategy you asked for, because every picky rule still has an ID you
   can kill — but the disable list is where precision is regained.

3. **Don't swap `de_CH_frami` into LanguageTool.** LT's German speller is
   already Hunspell-based and already ships the frami Swiss dict
   (`de_CH_frami_README.txt` is in the image) with native de-CH (accepts
   `ss`, rejects `ß`). Swapping it buys nothing and risks LT's compound
   logic. → The downloaded dicts serve **Vale / LibreOffice / LaTeX**;
   Helvetisms go in `spelling.txt` (LT's supported extension point).

4. **Vale can't spell-check German.** Confirmed: Vale's Go/Hunspell flags
   valid compounds like `Funktionswert`. → Vale is **style-only**;
   English spelling uses the en_GB dict, German spelling is off and left
   to LanguageTool.

5. **n-grams: don't mount them** (recommendation, argued both ways).
   *For:* real confusion-pairs (their/there). *Against:* they're
   corpus-majority statistics — probabilistic, not a fixed named rule,
   and against your precision-first stance; plus ~25 GB and RAM. The old
   compose pointed `languageModel` at an *empty* dir anyway. → Removed
   the line so "off" is explicit; one commented line re-enables.

## de-CH in LanguageTool — what it does and does not catch

Does: ss/ß orthography (native de-CH speller + our `SWISS_NO_ESZETT`),
Helvetism spelling (`Velo`, `Beiz`, `parkieren`… accepted), agreement,
compounds, punctuation, plus our Swiss guillemets / apostrophe-thousands
/ CHF rules. Does **not** meaningfully do: register/idiom Helvetic
preferences beyond a wordlist, canton-specific usage, or anything
requiring the n-grams we left off. It is thinner than de-DE for
style/idiom — the custom rules + Vale house-style layer fill the gap you
care about.

## Things the request left out, now fixed

* **The Traefik `languagetool.users` basic-auth file did not exist** —
  that router would 403/500 on every request. Generated (bcrypt).
* **LT 6.8 is out** (Jun 2026); bumped from 6.7.
* Added `cacheSize` / `maxCheckThreads` / pipeline tuning for speed
  (warm requests measured ~5 ms).

## Bugs found and fixed while building (all verified by `test.sh`)

* The entrypoint's grammar-merge assumed a **single-line `<rules>` tag**
  and also matched `<rules …>` mentioned in comments — it produced
  malformed XML and crash-looped LT. This is why the "existing" setup
  wasn't running. Rewrote the extractor (line-anchored, multi-line-safe).
* LT's **token regex rejects `\p{L}`** → rewrote the ß rule as `.*ß.*`.
* Grouped numbers tokenize into pieces → rewrote CHF/thousands rules with
  `<regexp>` (raw-text) like LT's own number rules.
* The merge passed content through **`awk -v`, which escape-processes
  `\1`** into a 0x01 byte, corrupting regex back-references → switched to
  a byte-exact `head/cat/tail` splice.
* LT's default en-GB **`OXFORD_SPELLING_*` enforces -ize** and flags
  correct British `organise`; **`ZAHL_PUNKT_KOMMA`** suggests non-Swiss
  separators → both disabled (evidence-based, in `disabled-rules.txt`).

## Redundancy / maintenance notes

* `SWISS_NO_ESZETT` overlaps LT's native de-CH speller (kept: it's a
  single, named, disableable rule with a guaranteed `ss` suggestion).
* `EN_GB_AEROPLANE` overlaps LT's built-in `EN_GB_SIMPLE_REPLACE_AIRPLANE`
  (kept as a worked custom-rule example; harmless).
* Vale's `HouseStyle.Ise` duplicates the LT `EN_GB_ISE_CONSISTENCY` rule
  on purpose — the two layers are independent by design.
* The Pi + Mac split doubles the files to keep in sync; the shared/ tree
  minimises it, but it is the main ongoing maintenance cost.

## Post-review fixes applied (independent agent review, 2026-08-17)

An independent best-practice/security review found **no blockers**. Fixed
and verified the same session:

* **CORS preflight vs basic-auth** (the top real-world risk). A browser
  fetch client sending `Authorization` triggers an unauthenticated
  `OPTIONS` preflight; basic-auth 401'd it, and LT itself answers
  `OPTIONS` with `400` + no `Access-Control-Allow-Headers`. Added a
  higher-priority `languagetool-preflight` router (`Method(OPTIONS)`) with
  a `languagetool-cors` middleware that answers preflights **without**
  auth. Verified: preflight → `200` with `Allow-Headers: Authorization`;
  unauth POST → `401`; authed POST → `200` with a single `ACAO`.
* **Pi memory limit** — `mem_limit: 2560m` + `mem_reservation: 1g`
  (above `Xmx` so the JVM isn't OOM-killed) so LT can't freeze the shared
  Pi. `security_opt: no-new-privileges:true` on both instances.
* **Credentials file** — `CREDENTIALS.local.txt` set to `0600` (delete
  after saving the password).

Left as accepted / minor (rule-scoped and disableable, per the contract):
`SWISS_THOUSANDS_APOSTROPHE` will also fire on comma-grouped phone numbers
(`044,123,456`); the Vale `Ise.yml` suggestion lowercases sentence-start
words (Vale is advisory; LT's `EN_GB_ISE_CONSISTENCY` preserves case);
`Vale/download-dicts.sh` pulls dicts from `master` (unpinned but
re-downloadable). Full report is in the session transcript.
