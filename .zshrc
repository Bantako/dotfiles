# Add user configurations here
# For HyDE not to touch your beloved configurations,
# we added 2 files to the project structure:
# 1. ~/.hyde.zshrc - for customizing the shell related hyde configurations
# 2. ~/.zshenv - for updating the zsh environment variables handled by HyDE // this will be modified across updates

#  Plugins 
# oh-my-zsh plugins are loaded  in ~/.hyde.zshrc file, see the file for more information

plugins=(git aliases copypath history zsh-completions zsh-autosuggestions zsh-syntax-highlighting)

#  Aliases 
# Add aliases here
# alias z=zoxide
alias lg=lazygit

#  This is your file 
# Add your configurations here


function y() {
	local tmp="$(mktemp -t "yazi-cwd.XXXXXX")" cwd
	yazi "$@" --cwd-file="$tmp"
	if cwd="$(command cat -- "$tmp")" && [ -n "$cwd" ] && [ "$cwd" != "$PWD" ]; then
		builtin cd -- "$cwd"
	fi
	rm -f -- "$tmp"
}

eval "$(zoxide init zsh)"

if [ -f .zshrc_secrets ]; then
  source .zshrc_secrets
fi

export EDITOR=nvim
export TERMINAL=wezterm
export BROWSER="~/.local/share/applications/vivaldi.desktop"
