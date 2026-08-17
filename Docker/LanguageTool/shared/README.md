# shared/

Mounted **read-only** into both LanguageTool containers (Pi and Mac) and
the single source of truth for customization. Both machines read the same
files because both are git clones of `HomeLab-FastPi`.

## Layout

```
shared/
├── bin/lt-entrypoint.sh              wrapper executed as the entrypoint
├── config/disabled-rules.txt         global disabledRuleIds kill-switch
├── rules/<lang>/grammar.xml          merged into LT's base <lang> grammar
├── rules/<lang>/<variant>/grammar.xml merged into LT's <variant> grammar
└── spelling/<region>/spelling.txt    appended to LT's variant spelling file
```

## How the entrypoint applies it (at container start)

`bin/lt-entrypoint.sh` runs *inside* the container before LT, edits LT's
own on-disk files (writable; owned by the `languagetool` user), then
execs `bash /LanguageTool/start.sh`. Effects are scoped to the
container's ephemeral filesystem — the host's `shared/` is never written.

1. **Spelling** → appended to LT's **variant** custom file, chosen per
   region (names are not uniform):

   | Region | Target inside container |
   |--------|-------------------------|
   | de_CH  | `resource/de/hunspell/spelling-de-CH.txt` |
   | en_GB  | `resource/en/hunspell/spelling_en-GB.txt` |

   Falls back to `<lang>/hunspell/spelling_custom.txt` if a variant file
   is ever missing. Words are accepted only for that variant; compounds
   built from them are accepted too.

2. **Rules** → the inner children of each fragment's `<rules lang="…">`
   wrapper are spliced before the final `</rules>` of the matching
   built-in file:

   | Fragment | Merged into |
   |----------|-------------|
   | `rules/de/de-CH/grammar.xml` | `rules/de/de-CH/grammar.xml` (de-CH only) |
   | `rules/en/en-GB/grammar.xml` | `rules/en/en-GB/grammar.xml` (en-GB only) |

   Variant fragments fire **only** for that variant. Put language-wide
   rules in `rules/<lang>/grammar.xml` instead.

3. **Disabled rules** → non-comment lines of `config/disabled-rules.txt`
   are joined into `langtool_disabledRuleIds`, which start.sh writes into
   `config.properties`; LT disables them globally.

## Fragment format

Keep the outer `<rules lang="…">` wrapper (so editors/xmllint validate);
it is discarded at merge — only inner `<category>/<rule>/<rulegroup>` are
used. The extractor is line-anchored, so a `<rules lang=…>` mentioned in
a comment is ignored; but the real opening tag and `</rules>` must each
begin their own line. See the top-level `README.md` for the rule-XML
primer and three hard-won gotchas (`\p{L}`, grouped numbers, `&lt;`).

## Verify

```bash
bash ../Raspi/scripts/test.sh          # full suite
# spot-check one rule:
curl -s http://localhost:8010/v2/check \
  --data-urlencode 'language=de-CH' --data-urlencode 'level=picky' \
  --data-urlencode 'text=Ich fahre mit dem Fahrrad.' | jq '.matches[].rule.id'
```
