# fish completion for notify.sh. Install: ln -s <this file> ~/.config/fish/completions/notify.sh.fish
complete -c notify.sh -f
complete -c notify.sh -n "__fish_is_first_arg" -a action -d "Telegram now (owner must act)"
complete -c notify.sh -n "__fish_is_first_arg" -a digest -d "note in the 19:00 daily digest"
complete -c notify.sh -n "__fish_is_first_arg" -s h -l help -d "usage"
