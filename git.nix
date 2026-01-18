{pkgs, ...}: {
  programs.git = {
    enable = true;
    settings.user.name = "morikawa";
    settings.user.email = "morimoriyuki552@gmail.com";
  };

  # Github CLI
  programs.gh = {
    enable = true;
    extensions = with pkgs; [gh-markdown-preview];
    settings = {
      editor = "nvim";
    };
  };
}
