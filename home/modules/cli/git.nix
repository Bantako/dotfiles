{pkgs, ...}: {
  programs.git = {
    enable = true;
    settings.user.name = "morikawa";
    settings.user.email = "morimoriyuki552@gmail.com";
  };

  programs.git.delta = {
    enable = true;
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
