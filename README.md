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
| `dot_tmux.conf` | Tmux with TPM, tmux-sensible, tmux-which-key, mouse support |
| `dot_config/ghostty/` | [Ghostty](https://ghostty.org/) terminal config (Option-as-Alt) |
| `dot_config/workmux/` | [Workmux](https://github.com/raine/workmux) default pane layout and agent config |
| `dot_workmux.yaml` | Workmux project-level template (worktree naming, hooks, merge strategy) |
| `dot_claude/` | Claude Code settings, hooks, and global instructions |
| `bin/clauto` | Automated Claude Code workflow script (see below) |
| `dot_zsh/completions/` | Zsh completions for custom scripts |

## clauto

A script that runs Claude Code headlessly against a git repo, then walks you through the results:

```
clauto [-d <directory>] <prompt>
```

1. Validates clean git working tree
2. Runs Claude with the given prompt (full permissions, headless)
3. Shows a colored diff of all changes (unstaged, staged, new files)
4. Prompts to accept or reject
   - **Accept** — stages changes, generates a commit message via Claude, commits, and optionally pushes
   - **Reject** — reverts everything (`git checkout` + `git clean`)

## Shell highlights

- **Oh-My-Zsh** with `robbyrussell` theme and git plugin
- **Vi mode** with cursor shape changes (block in normal, beam in insert)
- **Lazy-loaded nvm** — only initializes when `node`/`npm`/`npx`/`nvm` is first called
- **Zoxide** for fast directory jumping
- **Aliases:** `ghs` (GitHub Copilot suggest), `wm` (workmux), `cld`/`clpd` (Claude shortcuts)
- **Templated secrets** via chezmoi (GitHub PAT, API keys, Jira token)

## Tmux

- TPM auto-installed via `run_once_install-tpm.sh`
- Plugins: tmux-sensible, tmux-which-key
- Mouse enabled, 10k line history, 0ms escape time, 256-color + RGB

## Packages

Installed automatically via `run_onchange_install-packages.sh` using Homebrew:

**Formulae:** awscli, chezmoi, chrome-cli, dory, fd, gh, terraform, hey, jira-cli, neovim, portaudio, workmux, scc, tmux, tree, zoxide

**Casks:** Ghostty, Raycast

## Adding changes

```sh
# Edit a managed file, then:
chezmoi re-add
```
