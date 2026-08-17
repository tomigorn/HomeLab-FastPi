# LanguageTool — self-hosted en-GB / de-CH, precision-first, no AI

A deterministic, pre-AI-era grammar and spell-checking stack. Every
finding traces to a named rule you can inspect and permanently disable.
No cloud, no LLM, no statistical "corpus-majority" suggestions.

```
Browser / VS Code / Obsidian / CLI ──HTTP──► LanguageTool (Docker)
                                              rule-based engine, picky per client
LibreOffice / LaTeX / Vale ──local──► Hunspell dicts (en_GB, de_CH_frami)
```

Two layers:

1. **LanguageTool 6.8** (`erikvl87/languagetool:6.8`) — the shared HTTP
   engine. Custom Swiss/British rules merged in at container start; a
   curated global `disabledRuleIds` kill-switch; **no n-grams, no
   word2vec, no remote/AI rules** (see `REVIEW.md`).
2. **Vale** — a second, fully hand-authored client-side layer for
   house-style rules that must fire deterministically. Style only;
   English spelling via the en_GB Hunspell dict; **German spelling
   deliberately off** (Vale's Go/Hunspell mishandles German compounds).

| Where | URL                                    | When used                    |
|-------|----------------------------------------|------------------------------|
| Pi    | `https://languagetool.holy-grail.ch`   | phone, work laptop, anywhere |
| Mac   | `http://localhost:8010`                | browser extension on the Mac |

Read `REVIEW.md` first — it explains what changed from the original plan
and why. `MIGRATION.md` lists exactly what was replaced and how to roll
back.

---

## Layout

```
Raspi/            Pi-specific compose (public via Traefik + Cloudflared)
MacOS/            Mac-specific compose (loopback :8010 only)
shared/           customization — identical on Pi & Mac, synced via git
├── bin/lt-entrypoint.sh       wrapper: spelling + rules + disabled-rules
├── config/disabled-rules.txt  the global kill-switch (editable block)
├── rules/de/de-CH/grammar.xml  custom Swiss German rules (variant-scoped)
├── rules/en/en-GB/grammar.xml  custom British English rules
└── spelling/<region>/spelling.txt  words accepted as correctly spelled
Vale/             the house-style layer (runs on the client)
├── .vale.ini
├── styles/HouseStyle/   British English style + spelling
├── styles/Helvetia/     Swiss German style (no spelling)
└── download-dicts.sh    fetch en_GB + de_CH_frami Hunspell dicts
```

`shared/` is mounted **read-only**; the entrypoint copies it into the
container's own LT files at start, so the host tree is never written to.

---

## Run / update

```bash
# Pi
docker compose -f Raspi/docker-compose.yaml up -d
# Mac
docker compose -f MacOS/docker-compose.yaml up -d

# After editing anything in shared/ : re-apply by restarting
docker compose -f Raspi/docker-compose.yaml restart

# Verify everything (17 assertions; exits non-zero on any failure)
bash Raspi/scripts/test.sh
```

Both machines pull the `HomeLab-FastPi` git repo; there is **no
auto-sync**. After a change: `git pull` on each machine, then restart.

To update LanguageTool: bump the pinned tag in both compose files
(`erikvl87/languagetool:6.8` → newer), `up -d`, then run `test.sh`.
Tags: <https://hub.docker.com/r/erikvl87/languagetool/tags>. Never `:latest`.

---

## Picky mode is set PER CLIENT (not on the server)

LanguageTool's `level=picky` is a **per-request** parameter — it cannot
be forced server-side (verified against the LT source). Turn it on in
each client:

* **Browser extension** — Settings → toggle *Picky Mode*.
* **CLI / scripts** — add `--data-urlencode 'level=picky'`.
* **VS Code / Obsidian** — set the picky/level option in the extension.

Picky adds opinionated style rules (higher recall, lower precision). This
setup embraces that and claws precision back via `disabled-rules.txt` —
so every finding still maps to a rule ID you can kill.

Client setup for each tool you listed is in `CLIENTS.md`.

---

## Adding your own spelling (Helvetisms, house terms)

`shared/spelling/de_CH/spelling.txt` and `.../en_GB/spelling.txt` — one
word per line. At container start these are appended to LT's **variant**
custom-spelling files (`spelling-de-CH.txt`, `spelling_en-GB.txt`), so a
word added for de-CH is accepted only for de-CH. Compounds built from a
listed word are accepted too (add `Velo`, get `Veloweg` for free).

```bash
$EDITOR shared/spelling/de_CH/spelling.txt
git commit -am "spelling: add Bütschgi" && git push
# on each machine: git pull && docker compose … restart
```

---

## Writing custom rules (XML primer)

Custom rules live in the **variant** grammar files:
`shared/rules/de/de-CH/grammar.xml` and `shared/rules/en/en-GB/grammar.xml`.
Each file is a *fragment*: the outer `<rules lang="…">` wrapper is
discarded at merge time; its inner `<category>/<rule>/<rulegroup>`
children are spliced into LT's built-in grammar for that variant. Keep
the wrapper so the file validates in an editor.

A rule is either **token-based** (`<pattern><token>…`) or
**raw-text** (`<regexp>…`). Skeleton:

```xml
<rule id="MY_RULE_ID" name="Human name">
  <pattern>
    <token inflected="yes">Fahrrad</token>          <!-- matches all forms -->
    <token regexp="yes">rot|blau</token>            <!-- regex alternation -->
  </pattern>
  <message>Prefer <suggestion>Velo</suggestion>.</message>
  <short>Helvetism</short>
  <example correction="Velo">Ein <marker>Fahrrad</marker>.</example> <!-- MUST match -->
  <example>Ein Velo.</example>                                        <!-- must NOT match -->
</rule>
```

Key elements: `<token>` (one word; attrs `inflected`, `regexp`,
`case_sensitive`), `<suggestion>` (the fix, shown to the user),
`<match no="N" regexp_match=… regexp_replace=…>` (transform a captured
token), `<marker>` (what gets underlined). Group related rules in a
`<rulegroup id="…">`; the reported rule ID is the group ID.

Three gotchas learned building this (all encoded in the working rules):

1. **LT's token regex rejects `\p{L}`** ("Illegal repetition"). Use
   `.*ß.*` instead of `\p{L}*ß\p{L}*`.
2. **Grouped numbers are multiple tokens.** `1,000,000` and `1.500,00`
   can't be matched by a single `<token>`. Use `<regexp>` (raw-text,
   `\1`-style back-references) like LT's own `ZAHL_PUNKT_KOMMA`.
3. **`<` inside a regexp** (e.g. lookbehind `(?<!…)`) must be written
   `(?&lt;!…)` — it's XML.

Full reference: <https://dev.languagetool.org/development-overview>.
After editing, `restart` and run `test.sh` — add an assertion there for
every new rule (a `must_fire` and, ideally, a `must_not_match`).

---

## Finding a rule ID and disabling it permanently

When LanguageTool suggests something wrong:

```bash
curl -s http://localhost:8010/v2/check \
  --data-urlencode 'language=de-CH' \
  --data-urlencode 'level=picky' \
  --data-urlencode 'text=YOUR SENTENCE THAT GOT THE WRONG SUGGESTION' \
| jq -r '.matches[] | "\(.rule.id)\t\(.rule.description)"'
```

Copy the rule ID (the part before the tab), add it as a line in
`shared/config/disabled-rules.txt`, commit, `git pull` + `restart` on
each machine. The entrypoint compiles that file into the server's global
`disabledRuleIds`, so the rule never fires again — for any client, any
request. Re-run the curl to confirm it's gone.

Already disabled there (with rationale in the file): the whole
`OXFORD_SPELLING_*` family (it enforces -ize and flags correct British
-ise), and `ZAHL_PUNKT_KOMMA` (it suggests non-Swiss thousands
separators). See `disabled-rules.txt`.

---

## What's guaranteed OFF (no AI)

The self-hosted community image makes **zero** external calls. On top of
that this setup leaves every optional statistical/ML feature off:

* **n-grams** — not mounted (`langtool_languageModel` commented out).
  n-gram confusion rules are corpus-majority statistics, the opposite of
  precision-first. Re-enable via `scripts/download-ngrams.sh` + the
  commented compose lines if you ever want them.
* **word2vec / neural / `remoteRulesFile`** — never configured.
* Bundled `fastText` is language *detection* only (deterministic) and
  unused, since every client sends an explicit language.

---

## Backup

Everything except secrets and re-downloadables lives in the
`HomeLab-FastPi` git repo — that is the backup. N-grams
(`scripts/download-ngrams.sh`) and Hunspell dicts (`Vale/download-dicts.sh`)
are re-downloadable and gitignored. The image tag is pinned, so a rebuild
is byte-identical. Basic-auth credentials: `Traefik/traefik/dynamic/languagetool.users`
(bcrypt, gitignored) — plaintext was written once to `CREDENTIALS.local.txt`
(gitignored; delete after saving).
