# Migration note — 2026-08-17 rebuild

What was changed, replaced, backed up, and how to roll back. Backups use
the timestamp suffix `.bak.20260817-010200`.

## Files backed up (originals preserved)

```
Raspi/docker-compose.yaml.bak.20260817-010200
MacOS/docker-compose.yaml.bak.20260817-010200
Raspi/scripts/test.sh.bak.20260817-010200
README.md.bak.20260817-010200
shared/bin/lt-entrypoint.sh.bak.20260817-010200
shared/rules/de/grammar.xml.bak.20260817-010200
```

## Changed / replaced

| File | Change |
|------|--------|
| `Raspi/docker-compose.yaml` | image → `:6.8`; n-grams unmounted + `languageModel` commented; added cache/thread/pipeline tuning; removed `ngrams` volume |
| `MacOS/docker-compose.yaml` | same, keeping loopback `127.0.0.1:8010` |
| `shared/bin/lt-entrypoint.sh` | rewritten: variant rule paths, byte-exact splice, `disabled-rules.txt` → `disabledRuleIds`, multi-line/comment-safe extractor, variant spelling targets |
| `Raspi/scripts/test.sh` + `MacOS/scripts/test.sh` | replaced with 17-assertion end-to-end suite |
| `README.md` | rewritten for the new architecture |

## Created

```
shared/config/disabled-rules.txt        global rule kill-switch
shared/rules/de/de-CH/grammar.xml        Swiss rules (moved from base + new)
shared/rules/en/en-GB/grammar.xml        British rules
Vale/.vale.ini, Vale/styles/**, Vale/download-dicts.sh   the Vale layer
Traefik/traefik/dynamic/languagetool.users   basic-auth (bcrypt, gitignored)
REVIEW.md, MIGRATION.md, CLIENTS.md, Vale/README.md
CREDENTIALS.local.txt                    plaintext basic-auth (gitignored)
```

## Removed / moved

* `shared/rules/de/grammar.xml` — **deleted** (backed up). Its rules moved
  to `shared/rules/de/de-CH/grammar.xml` (variant-scoped: they no longer
  fire for de-DE). The Helvetism/ß/CHF rules were rewritten in the move.

## Runtime state changed

* Container recreated on `erikvl87/languagetool:6.8` (was stopped before).
* `git` working tree in `~/Projects` now has new/modified/deleted files —
  review and commit (see below).

## Roll back

Fastest — restore the pre-rebuild files:

```bash
cd ~/Projects/Docker/LanguageTool
ts=20260817-010200
for f in Raspi/docker-compose.yaml MacOS/docker-compose.yaml \
         Raspi/scripts/test.sh README.md shared/bin/lt-entrypoint.sh; do
  cp "$f.bak.$ts" "$f"
done
cp shared/rules/de/grammar.xml.bak.$ts shared/rules/de/grammar.xml
rm -rf shared/rules/de/de-CH shared/rules/en/en-GB shared/config
docker compose -f Raspi/docker-compose.yaml up -d
```

(That returns you to the previous state — which, note, did not actually
run; the crash-loop bug is fixed only in the new entrypoint.)

Or, once committed, `git revert` the rebuild commit and `git pull` +
`docker compose … up -d` on each machine.

## Commit

Nothing is committed automatically. Suggested:

```bash
cd ~/Projects
git add Docker/LanguageTool Docker/Traefik/traefik/dynamic/languagetool.yml
# NOTE: *.users, *.bak.*, Vale/dicts/, CREDENTIALS.local.txt are gitignored
git status        # confirm no secrets staged
git commit -m "LanguageTool: rebuild en-GB/de-CH precision-first, add Vale + disabled-rules"
```
