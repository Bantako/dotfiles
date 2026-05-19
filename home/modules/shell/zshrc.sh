# plugins
eval "$(sheldon source)"

# options
# 単語の区切り文字を指定する
autoload -Uz select-word-style
# ここで指定した文字は単語区切りとみなされる
select-word-style default
# /も区切りと扱うので、^Wでディレクトリ１つ分を削除できる
zstyle ':zle:*' word-chars " /=;@:{},|"
zstyle ':zle:*' word-style unspecified
# 大文字小文字を無視してマッチ
zstyle ':completion:*' matcher-list 'm:{a-z}={A-Z}'


# scroll prompt
function __prompt_preexec() {
  printf "\033]133;C;\007"
}

function __prompt_precmd() {
  printf "\033]133;A;\007"
}

preexec_functions+=(__prompt_preexec)
precmd_functions+=(__prompt_precmd)

# functions
function y() {
  local tmp="$(mktemp -t "yazi-cwd.XXXXXX")" cwd
  yazi "$@" --cwd-file="$tmp"
  if cwd="$(command cat -- "$tmp")" && [ -n "$cwd" ] && [ "$cwd" != "$PWD" ]; then
    builtin cd -- "$cwd"
  fi
  rm -f -- "$tmp"
}

# Cで標準出力をクリップボードにコピーする
if command -v wl-copy >/dev/null 2>&1 ; then
  alias -g C='| wl-copy'
fi
