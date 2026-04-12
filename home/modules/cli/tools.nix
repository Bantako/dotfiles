{pkgs, ...}: {
  home.packages = with pkgs; [
    # 基本CLIツール
    bat
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
  ];
}
