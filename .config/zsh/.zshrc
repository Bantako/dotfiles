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
# フローコントロールを無効にする
setopt no_flow_control
# Ctrl+Dでzshを終了しない
setopt ignore_eof
# '#'をコメントして扱う
setopt interactive_comments
# cdしたら自動的にpushdする
setopt auto_pushd
# 重複したディレクトリを追加しない
setopt pushd_ignore_dups
# 同じコマンドをヒストリに残さない
setopt hist_ignore_all_dups
# スペースから始まるコマンド行はヒストリに残さない
setopt hist_ignore_space
# 同時に起動したzshの間でヒストリを共有する
setopt share_history
# ヒストリに保存するときに余分なスペースを削除する
setopt hist_reduce_blanks
# 高機能なワイルドカード展開を使用する
setopt extended_glob

# scroll prompt
function __prompt_preexec() {
  printf "\033]133;C;\007"
}

function __prompt_precmd() {
  printf "\033]133;A;\007"
}

preexec_functions+=(__prompt_preexec)
precmd_functions+=(__prompt_precmd)

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
# sudo のあとのコマンドでエイリアスを有効にする
alias sudo='sudo '
alias ls='eza --icons --color=auto'
alias ls='eza -a --icons --color=auto'
alias ll='eza -lah --git --icons --color=auto'
alias lg='lazygit'

# グローバルエイリアス
alias -g L='| less'
alias -g G='| grep'

# Cで標準出力をクリップボードにコピーする
if which xsel >/dev/null 2>&1 ; then
  alias -g C='| xsel --input --clipboard'
fi

# variables
export EDITOR=nvim
export BROWSER=vivaldi
export LESSHISTFILE="$XDG_STATE_HOME"/less/history
