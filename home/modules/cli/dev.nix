{ pkgs, ... }: {
  home.packages = with pkgs; [
    # LSP
    nil                          # Nix
    rust-analyzer                # Rust
    lua-language-server          # Lua
    vscode-langservers-extracted # JSON / HTML / CSS
    basedpyright                 # Python
    bash-language-server         # Bash
    marksman                     # Markdown
    yaml-language-server         # YAML
    taplo                        # TOML

    # formatter
    rustfmt
    nixfmt-rfc-style
    shfmt
    stylua                       # Lua
    prettier                     # JS/TS/JSON/MD/YAML
    ruff                         # Python
  ];
}
