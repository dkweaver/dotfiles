# dotfiles

Personal dotfiles managed with [chezmoi](https://www.chezmoi.io/).

## Setup

```sh
chezmoi init --apply https://github.com/<user>/dotfiles.git
```

## What's included

| File / Directory | Description |
|---|---|
| `dot_zshrc.tmpl` | Zsh config (oh-my-zsh, vi mode, lazy-loaded nvm, zoxide, aliases) |
| `dot_gitconfig.tmpl` | Git configuration (templated for secrets) |
| `dot_tmux.conf` | Tmux configuration |
| `dot_config/ghostty/` | [Ghostty](https://ghostty.org/) terminal config |
| `dot_config/workmux/` | [Workmux](https://github.com/raine/workmux) config |
| `dot_claude/` | Claude Code settings |
| `bin/` | Custom scripts (`clauto`) |
| `dot_zsh/completions/` | Zsh completions |

## Packages

Installed automatically via `run_onchange_install-packages.sh` using Homebrew:

**Formulae:** awscli, chezmoi, chrome-cli, dory, fd, gh, terraform, hey, jira-cli, neovim, portaudio, workmux, scc, tmux, tree, zoxide

**Casks:** Ghostty, Raycast

## Adding changes

```sh
# Edit a managed file, then:
chezmoi re-add
```
