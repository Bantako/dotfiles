{pkgs, ...}: {
  programs.git = {
    enable = true;
    settings.user.name = "morikawa";
    settings.user.email = "morimoriyuki552@gmail.com";
    settings.init.defaultBranch = "main";
    settings.commit.template = "~/.config/git/commit-template";
  };

  home.file.".config/git/commit-template".text = ''
    # <type>(<scope>): <日本語メッセージ>
    #
    # type: feat / fix / chore / docs / refactor / style / test
    # scope: 変更対象モジュール（任意）例: ai, tools, yazi, nixos
    #
    # 例: feat(ai): hermes-agent を Home Manager に追加
    #     fix(minecraft): 起動失敗を修正
    #     chore(tools): 不要パッケージを削除
  '';

  programs.delta = {
    enable = true;
    enableGitIntegration = true;
    options = {
      navigate = true;    # n/N でdiff間を移動
      side-by-side = true;
    };
  };

  # Github CLI
  programs.gh = {
    enable = true;
    extensions = with pkgs; [gh-markdown-preview];
    settings = {
      editor = "nvim";
    };
  };

  # Git client TUI
  programs.lazygit = {
    enable = true;
  };

}
