# Vale — deterministic house-style layer

Vale is the second layer: hand-authored style rules that fire
deterministically, each traceable to a YAML file in `styles/`. It runs on
the client (Mac / VS Code / CLI) — there is no Vale server, and it is
independent of LanguageTool.

## Install & first run

```bash
brew install vale          # macOS ;  or see https://vale.sh/docs/install
cd .../LanguageTool/Vale
bash download-dicts.sh      # fetch en_GB + de_CH_frami into ./dicts (gitignored)
vale README.md             # British English style + spelling
vale notes.de.md           # *.de.* files → Swiss German style (no spelling)
```

## What it checks

* **British English** (`styles/HouseStyle/`) — any `*.md/.txt/.tex/…`:
  * `Ise.yml` — enforce `-ise` spelling (explicit word list).
  * `Spelling.yml` — en_GB Hunspell spell check.
* **Swiss German** (`styles/Helvetia/`) — files named `*.de.*`:
  * `Eszett.yml` — flag `ß` (Swiss uses `ss`).
  * `Germanismen.yml` — nudge Germanisms → Helvetisms (`Fahrrad`→`Velo`).

**No German spelling.** Vale's Go/Hunspell mishandles German compounding
(flags valid `Funktionswert` etc.). German spelling is LanguageTool's
job. Do not add a `spelling`-based rule to `Helvetia/`.

## Language selection

Vale has no language auto-detect; it picks a style by file glob (see
`.vale.ini`). Convention: **Swiss-German files end in `.de.md` / `.de.txt`
/ `.de.tex`**, everything else is British English.

## Writing a rule

Each rule is one YAML file under `styles/<StyleName>/`. Common types:

```yaml
# substitution — suggest a replacement
extends: substitution
message: "Use '%s' instead of '%s'."
level: warning
swap:
  utilise: use

# existence — flag a pattern (Go RE2 regex; \p{L} IS supported here)
extends: existence
message: "Avoid '%s'."
level: error
tokens:
  - '\bvery\s+\w+'
```

Add the filename's style to `BasedOnStyles` (or it's picked up
automatically within a `BasedOnStyles` style directory). Reference:
<https://vale.sh/docs>.

## Notes

* `dicts/` and `styles/config/vocabularies/House/` accepted words are
  gitignored / re-creatable via `download-dicts.sh`.
* Accept product names / jargon in
  `styles/config/vocabularies/House/accept.txt` so the en_GB speller
  doesn't flag them.
