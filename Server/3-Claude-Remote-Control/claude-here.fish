# fish completion for claude-here
complete -c claude-here -f
complete -c claude-here -n '__fish_is_first_arg' -a '(claude-here --complete folders)' -d 'allowed folder'
complete -c claude-here -n '__fish_is_first_arg' -l list -d 'running sessions'
complete -c claude-here -n '__fish_is_first_arg' -l stop -d 'stop a session'
complete -c claude-here -n '__fish_is_first_arg' -l done -d 'batch: stop me at the next check'
complete -c claude-here -n '__fish_is_first_arg' -s h -l help -d 'help'
complete -c claude-here -n '__fish_seen_argument -l stop' -a '(claude-here --complete running)' -d 'running session'
complete -c claude-here -n 'not __fish_is_first_arg; and not __fish_seen_argument -l stop -l list -l done -l help' -a 'auto' -d 'default: auto permission mode'
complete -c claude-here -n 'not __fish_is_first_arg; and not __fish_seen_argument -l stop -l list -l done -l help' -a 'batch' -d 'bypass mode, cannot ask'
