# bash completion for claude-here
_claude_here() {
  local cur=${COMP_WORDS[COMP_CWORD]} prev=${COMP_WORDS[COMP_CWORD-1]}
  if (( COMP_CWORD == 1 )); then
    COMPREPLY=($(compgen -W "--list --stop --done --help $(claude-here --complete folders 2>/dev/null)" -- "${cur/#\~/$HOME}"))
  elif [[ $prev == --stop ]]; then
    COMPREPLY=($(compgen -W "$(claude-here --complete running 2>/dev/null)" -- "$cur"))
  elif (( COMP_CWORD == 2 )) && [[ $prev != -* ]]; then
    COMPREPLY=($(compgen -W "auto batch" -- "$cur"))
  fi
}
complete -F _claude_here claude-here
