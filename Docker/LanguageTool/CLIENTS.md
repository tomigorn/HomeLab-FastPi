# Client setup

Point every client at your own server and turn on **Picky Mode** where
offered (picky is per-client — the server can't force it). Always send an
explicit language (`en-GB` or `de-CH`).

Endpoints:

* **Pi (anywhere):** `https://languagetool.holy-grail.ch` — basic-auth
  (`Traefik/traefik/dynamic/languagetool.users`; plaintext in
  `CREDENTIALS.local.txt`).
* **Mac (local):** `http://localhost:8010` — no auth.

---

## Browser extension (Chrome / Firefox / Edge)

Official *LanguageTool* extension → Settings (gear):

1. **Advanced settings → "Use your own LanguageTool server"** →
   `https://languagetool.holy-grail.ch` (Mac: `http://localhost:8010`).
2. It will prompt for the basic-auth login once per device — enter the
   `languagetool.users` credentials; the extension stores and re-sends
   them (that's why the Traefik middleware keeps the header).
3. Turn **Picky Mode** on. Set the mother-tongue / variant to British
   English and Swiss German so it doesn't auto-pick de-DE.

## VS Code

Extension: **`davidlday.languagetool-linter`** (or `adamvoss.vale` for
Vale — see below).

```jsonc
// settings.json
"languageToolLinter.languageTool.url": "http://localhost:8010",
// or the Pi URL; the linter supports basic-auth via username/password:
"languageToolLinter.languageTool.username": "lt",
"languageToolLinter.languageTool.password": "<from CREDENTIALS.local.txt>",
"languageToolLinter.languageTool.preferredVariants": "en-GB,de-CH",
"languageToolLinter.languageTool.level": "picky"
```

## Obsidian

Community plugin **"LanguageTool Integration"**:

* Settings → **"LanguageTool API URL"** → `https://languagetool.holy-grail.ch`.
* Basic-auth: put `user:pass` in the plugin's *username/password* fields.
* Enable **Picky Mode**; set the language to `en-GB` / `de-CH` (or
  autodetect, but variant-pin if it guesses de-DE).

## LibreOffice

Two independent things:

* **Spelling** — install the Hunspell dicts as extensions (or drop the
  `.dic/.aff` from `Vale/dicts/` into LibreOffice's dictionary path):
  `en_GB` and `de_CH_frami`. Set the document language to *English (UK)* /
  *German (Switzerland)*.
* **Grammar via LanguageTool** — extension
  [*LanguageTool for LibreOffice*](https://languagetool.org/languagetool-for-libreoffice-and-openoffice)
  → configure it to use the **remote server** URL instead of the built-in
  engine (Options → LanguageTool → Remote server).

## LaTeX

* **Editor-side grammar:** VS Code **LTeX+** (`ltex-plus.vscode-ltex`) or
  the Neovim/Emacs LTeX LSP → set `ltex.languageToolHttpServerUri` to your
  server URL and `ltex.language` to `en-GB` / `de-CH`. LTeX understands
  LaTeX markup so it won't choke on commands.
* **Spelling:** point your editor's Hunspell at `Vale/dicts/en_GB.*` /
  `Vale/dicts/de_CH_frami.*`.

## CLI

```bash
# British English, picky
curl -s http://localhost:8010/v2/check \
  --data-urlencode 'language=en-GB' \
  --data-urlencode 'level=picky' \
  --data-urlencode 'text=We organize the colour scheme.' \
| jq -r '.matches[] | "\(.rule.id): \(.message)"'

# Against the Pi (basic-auth)
curl -s -u lt:'<password>' https://languagetool.holy-grail.ch/v2/check \
  --data-urlencode 'language=de-CH' --data-urlencode 'level=picky' \
  --data-urlencode 'text=Ich fahre mit dem Fahrrad.'
```

Handy wrapper — drop in `~/.local/bin/lt`:

```bash
#!/usr/bin/env bash
lang="${LT_LANG:-en-GB}"
curl -s "${LT_URL:-http://localhost:8010}/v2/check" \
  --data-urlencode "language=$lang" --data-urlencode 'level=picky' \
  --data-urlencode "text=$*" \
| jq -r '.matches[] | "• \(.rule.id): \(.message)"'
```

## Vale (the house-style layer)

Vale runs locally, not against the server. Install and use:

```bash
brew install vale                         # macOS
cd ~/Projects/Docker/LanguageTool/Vale
bash download-dicts.sh                     # fetch en_GB + de_CH_frami dicts
vale README.md                             # lint a British-English file
vale notes.de.md                           # *.de.* → Swiss German style
```

VS Code: extension **`ChrisChinchilla.vale-vscode`**, point
`vale.valeCLI.config` at `Vale/.vale.ini`. See `Vale/README.md`.
