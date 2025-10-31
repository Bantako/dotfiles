# plugins

eval "$(sheldon source)"

# yazi function
function y() {
  local tmp="$(mktemp -t "yazi-cwd.XXXXXX")" cwd
  yazi "$@" --cwd-file="$tmp"
  if cwd="$(command cat -- "$tmp")" && [ -n "$cwd" ] && [ "$cwd" != "$PWD" ]; then
    builtin cd -- "$cwd"
  fi
  rm -f -- "$tmp"
}

# alias
alias ls='eza -a --icons --color=auto'
alias ll='eza -lah --git --icons --color=auto'
alias lg='lazygit'

# variables
export EDITOR=nvim
export BROWSER=vivaldi
