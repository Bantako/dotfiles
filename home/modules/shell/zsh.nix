{pkgs, config, lib, claudeAliases ? {}, ...}: {
  home.packages = [ pkgs.sheldon ];
  home.file.".config/sheldon/plugins.toml".source = ../cli/sheldon/plugins.toml;

  programs.nix-index = {
    enable = true;
    enableZshIntegration = true;
  };
  programs.zsh = {
    enable = true;
    # 補完初期化はsheldonで管理する
    enableCompletion = false;
    autosuggestion.enable = false; # 入力サジェスト
    syntaxHighlighting.enable = false; # シンタックスハイライト

    # alias
    shellAliases = lib.mkMerge [
      {
        # sudo のあとのコマンドでエイリアスを有効にする
        sudo = "sudo ";
        cat = "bat";
        grep = "rg";
        ls = "eza --icons always --classify always";
        la = "eza --icons always --classify always --all ";
        ll = "eza --icons always --long --all --git ";
        tree = "eza --icons always --classify always --tree";
        lg = "lazygit";
        # nh (nix helper)
        nos = "nh os switch";
        nhs = "nh home switch";
        nob = "nh os boot";
        noc = "nh clean all";
      }
      claudeAliases
    ];

    # setopt 相当
    setOptions = [
      # ディレクトリ名だけ打つと自動でcd
      "AUTO_CD"
      # cdしたら自動的にpushdする
      "AUTO_PUSHD"
      # フローコントロールを無効にする
      "NO_FLOW_CONTROL"
      # Ctrl+Dでzshを終了しない
      "IGNORE_EOF"
      # 重複したディレクトリを追加しない
      "PUSHD_IGNORE_DUPS"
      # 同じコマンドをヒストリに残さない
      "HIST_IGNORE_ALL_DUPS"
      # スペースから始まるコマンド行はヒストリに残さない
      "HIST_IGNORE_SPACE"
      # 同時に起動したzshの間でヒストリを共有する
      "SHARE_HISTORY"
      # ヒストリに保存するときに余分なスペースを削除する
      "HIST_REDUCE_BLANKS"
      # 高機能なワイルドカード展開を使用する
      "EXTENDED_GLOB"
    ];

    history = {
      size = 100000;
      save = 100000;
      ignoreDups = true;
      ignoreSpace = true;
      path = "$HOME/.local/share/zsh/history";
    };

    # export
    sessionVariables = {
      EDITOR = "nvim";
      BROWSER = "vivaldi";
      LESSHISTFILE = "$XDG_STATE_HOME/less/history";
      PAPERLESS_URL = "http://192.168.0.222:8010";
    };

    initContent = ''
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
# yazi function
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

# sops
if [ -r /run/secrets/openai_api_key ]; then
  export OPENAI_API_KEY="$(cat /run/secrets/openai_api_key)"
fi
if [ -r /run/secrets/deepseek_api_key ]; then
  export DEEPSEEK_API_KEY="$(cat /run/secrets/deepseek_api_key)"
fi
if [ -r /run/secrets/raindrop_token ]; then
  export RAINDROP_TOKEN="$(cat /run/secrets/raindrop_token)"
fi
if [ -r /run/secrets/paperless_token ]; then
  export PAPERLESS_TOKEN="$(cat /run/secrets/paperless_token)"
fi
    '';
  };
}
