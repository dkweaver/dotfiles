#!/bin/bash
brew bundle --file=/dev/stdin <<EOF
brew "awscli"
brew "chezmoi"
brew "chrome-cli"
brew "dory"
brew "fd"
brew "gh"
brew "hashicorp/tap/terraform"
brew "hey"
brew "jira-cli"
brew "neovim"
brew "portaudio"
brew "raine/workmux/workmux"
brew "scc"
brew "tmux"
brew "tree"
brew "zoxide"

cask "ghostty"
cask "raycast"
EOF
