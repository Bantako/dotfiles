{pkgs, config, lib, claudeAliases ? {}, ...}:

let
  sopsEnv = {
    OPENAI_API_KEY   = "/run/secrets/openai_api_key";
    DEEPSEEK_API_KEY = "/run/secrets/deepseek_api_key";
    RAINDROP_TOKEN   = "/run/secrets/raindrop_token";
    PAPERLESS_TOKEN  = "/run/secrets/paperless_token";
    IMMICH_TOKEN     = "/run/secrets/immich_token";
  };
in {
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
      IMMICH_URL    = "http://192.168.0.222:2283";
    };

    initContent =
      (builtins.readFile ./zshrc.sh)
      + lib.concatStringsSep "\n" (lib.mapAttrsToList (k: v:
          ''[ -r ${v} ] && export ${k}="$(cat ${v})"''
        ) sopsEnv);
  };
}
