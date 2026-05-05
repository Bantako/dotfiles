{pkgs, config, ...}: let
  raindrop-to-daily = pkgs.writeShellScriptBin "raindrop-to-daily" ''
    exec ${pkgs.python3}/bin/python3 \
      ${config.home.homeDirectory}/.dotfiles/home/modules/cli/scripts/raindrop-to-daily.py \
      "$@"
  '';
in {
  xdg.configFile."ov/config.yaml".source = ./ov.yaml;

  home.packages = with pkgs; [
    raindrop-to-daily
    # 基本CLIツール
    bottom
    eza
    fzf
    httpie
    ripgrep
    zoxide
    jq

    # ターミナルツール群
    atool         # アーカイブ展開（aunpack、yaziから使用）
    bitwarden-cli # パスワード管理CLI
    fio           # ディスクI/Oベンチマーク
    gh            # GitHub CLI
    htop          # プロセスモニター
    ov            # ページャー（yaziのbat連携）
    python3       # Pythonインタープリター
    nodejs        # Node.js（npx経由のMCPサーバー用）
    unzip         # ZIP展開
    uv            # Pythonパッケージマネージャー
  ];
}
