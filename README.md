# dotfiles

Personal dotfiles managed with [chezmoi](https://www.chezmoi.io/).

## Setup

```sh
chezmoi init --apply https://github.com/<user>/dotfiles.git
```

This will:
1. Clone the repo into chezmoi's source directory
2. Apply all dotfiles to `$HOME`
3. Run `run_once_install-tpm.sh` to install the Tmux Plugin Manager
4. Run `run_onchange_install-packages.sh` to install Homebrew packages

### Prerequisites

- macOS with [Homebrew](https://brew.sh/) installed
- Git

Everything else (tmux plugins, packages, shell tools) is installed automatically by chezmoi's run scripts.

## What's included

| File / Directory | Description |
|---|---|
| `dot_zshrc.tmpl` | Zsh config (oh-my-zsh, vi mode, lazy-loaded nvm, zoxide, aliases) |
| `dot_gitconfig.tmpl` | Git configuration (templated for user email) |
| `dot_tmux.conf` | Tmux with TPM, tmux-sensible, tmux-which-key, mouse support |
| `dot_config/ghostty/` | [Ghostty](https://ghostty.org/) terminal config (Option-as-Alt) |
| `dot_config/workmux/` | [Workmux](https://github.com/raine/workmux) default pane layout and agent config |
| `dot_workmux.yaml` | Workmux project-level template (worktree naming, hooks, merge strategy) |
| `dot_claude/` | Claude Code settings, hooks, and global instructions |
| `bin/clauto` | Automated Claude Code workflow script (see below) |
| `dot_zsh/completions/` | Zsh completions for custom scripts |

## clauto

A script that runs Claude Code headlessly against a git repo, then walks you through the results.

```
clauto [-d <directory>] <prompt>
```

### How it works

1. **Directory resolution** — uses `-d <dir>` if provided; if not in a git repo, falls back to a [zoxide](https://github.com/ajeetdsouza/zoxide) interactive directory picker
2. **Safety checks** — verifies you're in a git repo with a clean working tree
3. **Guardrails** — injects safety rules into the prompt (no editing outside the repo, no deleting files, no destructive commands, no touching `.env` or `.git/`)
4. **Runs Claude** headlessly with `--dangerously-skip-permissions`
5. **Runaway protection** — automatically reverts if more than 10 files were changed
6. **Review** — shows a colored unified diff of all changes
7. **Accept or reject:**
   - **Accept** — stages changes, generates a commit message via Claude, commits, and optionally pushes
   - **Reject** — reverts everything (`git checkout` + `git clean`)

Tab completion is available via `dot_zsh/completions/_clauto`.

## Shell highlights

- **Oh-My-Zsh** with `robbyrussell` theme and git plugin
- **Vi mode** with cursor shape changes (block in normal, beam in insert)
- **Lazy-loaded nvm** — stub functions for `node`/`npm`/`npx`/`nvm` that source the real nvm only on first call; also adds the latest nvm node's bin to `$PATH` so installed binaries are available without loading nvm
- **Zoxide** for fast directory jumping (`z`)
- **Templated secrets** via chezmoi data (GitHub PAT, OpenAI key, Datadog keys, Jira token) — only exported when the key exists in chezmoi's data store
- **Aliases:**

| Alias | Expands to |
|---|---|
| `ghs` | GitHub Copilot suggest |
| `wm` | workmux |
| `cld` | Claude Code (interactive, skip permissions) |
| `clpd` | Claude Code (headless, skip permissions) |

## Tmux

- TPM auto-installed via `run_once_install-tpm.sh`
- Plugins: tmux-sensible, tmux-which-key
- Mouse enabled, 10k line scrollback, 0ms escape time, 256-color + RGB

## Workmux

[Workmux](https://github.com/raine/workmux) manages tmux workspaces for git worktree workflows.

- **Global config** (`dot_config/workmux/config.yaml`): NerdFont icons, rebase merge strategy, Claude as the agent, default two-pane layout (Claude on top, shell on bottom)
- **Project template** (`dot_workmux.yaml`): comprehensive commented-out reference for per-project customization (appearance, git settings, hooks, tmux layout, sandbox config)

## Claude Code

- **Global instructions** (`dot_claude/CLAUDE.md`): enforces never pushing directly to main
- **Settings** (`dot_claude/private_settings.json`): Opus model, always-think mode, pre-tool-use hook that stashes a git baseline for rollback, curated permissions allowlist for read-only git/gh/jira commands

## Packages

Installed automatically via `run_onchange_install-packages.sh` using Homebrew:

**Formulae:** awscli, chezmoi, chrome-cli, dory, fd, gh, terraform, hey, jira-cli, neovim, portaudio, workmux, scc, tmux, tree, zoxide

**Casks:** Ghostty, Raycast

## Adding changes

```sh
# Edit a managed file, then:
chezmoi re-add
```

To add a new file to be managed:

```sh
chezmoi add ~/.some-config
```
