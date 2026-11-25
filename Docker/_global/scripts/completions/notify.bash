# bash completion for notify.sh: the mode, then for digest the script names already used as sources. Load: source this file (e.g. from ~/.bashrc).
_notify() {
  local cur=${COMP_WORDS[COMP_CWORD]}
  if (( COMP_CWORD == 1 )); then mapfile -t COMPREPLY < <(compgen -W 'action digest --help' -- "$cur"); return; fi
  if (( COMP_CWORD == 2 )) && [[ ${COMP_WORDS[1]} == digest ]]; then
    mapfile -t COMPREPLY < <(compgen -W "$(grep -o 'source="[^"]*"' /var/lib/node-exporter/textfile/digest_notes.prom 2>/dev/null | cut -d'"' -f2 | sort -u)" -- "$cur")
  fi
}
complete -F _notify notify.sh
