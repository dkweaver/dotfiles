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

### Secrets / chezmoi data

Sensitive values are injected at apply time via chezmoi's data store. To populate them:

```sh
chezmoi data  # view current values
```

Edit `~/.config/chezmoi/chezmoi.toml` and add a `[data]` section:

```toml
[data]
  github_pat       = "ghp_..."
  openai_api_key   = "sk-..."
  dd_api_key       = "..."
  dd_app_key       = "..."
  jira_api_token   = "..."
```

Each key is only exported to the environment if present — leaving a key out skips the export entirely.

## What's included

| File / Directory | Description |
|---|---|
| `dot_zshrc.tmpl` | Zsh config (oh-my-zsh, vi mode, lazy-loaded nvm/yvm, zoxide, aliases) |
| `dot_gitconfig.tmpl` | Git configuration (templated for user email) |
| `dot_tmux.conf` | Tmux with TPM, tmux-sensible, tmux-which-key, mouse support, clauto popup |
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

If called with no arguments, it prompts interactively.

### How it works

1. **Directory resolution** — uses `-d <dir>` if provided; if not in a git repo, falls back to a [zoxide](https://github.com/ajeetdsouza/zoxide) interactive directory picker
2. **Safety checks** — verifies you're in a git repo with a clean working tree
3. **Guardrails** — injects safety rules into the prompt (no editing outside the repo, no deleting files, no destructive commands, no touching `.env` or `.git/`)
4. **Runs Claude** headlessly with `--dangerously-skip-permissions` using the `sonnet` model
5. **Runaway protection** — automatically reverts if more than 10 files were changed
6. **Review** — shows a colored unified diff of all changes in `less`
7. **Accept or reject:**
   - **Accept** — stages changes, generates a commit message via Claude, commits, and optionally pushes
   - **Reject** — reverts everything (`git checkout` + `git clean`)

### Tmux integration

`clauto` is bound to `prefix + a` in tmux as a floating popup (90% wide, 85% tall) anchored to the current pane's directory. This is the primary way to invoke it during normal workflow.

Tab completion is available via `dot_zsh/completions/_clauto`.

## Shell highlights

- **Oh-My-Zsh** with `robbyrussell` theme and git plugin
- **Vi mode** with cursor shape changes (block in normal, beam in insert)
- **Lazy-loaded nvm** — stub functions for `node`/`npm`/`npx`/`nvm` that source the real nvm only on first call; also adds the latest nvm node's bin to `$PATH` so installed binaries are available without loading nvm
- **YVM** — yarn version manager, sourced from Homebrew (`/opt/homebrew/opt/yvm`)
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
- **`prefix + a`** — opens `clauto` in a floating popup (90% × 85%) at the current pane's path

## Workmux

[Workmux](https://github.com/raine/workmux) manages tmux workspaces for git worktree workflows.

- **Global config** (`dot_config/workmux/config.yaml`): NerdFont icons enabled, rebase as the default merge strategy, Claude as the agent, two-pane default layout (Claude on top, shell on bottom)
- **Project template** (`dot_workmux.yaml`): comprehensive commented-out reference for per-project customization — appearance, git settings, hooks (`post_create`, `pre_merge`, `pre_remove`), tmux layout, file copy/symlink on worktree creation, dashboard keybindings, and sandbox config

## Claude Code

- **Global instructions** (`dot_claude/CLAUDE.md`): enforces never pushing directly to main
- **Settings** (`dot_claude/private_settings.json`):
  - Model: `opus`
  - `alwaysThinkingEnabled: true` — extended thinking on for every request
  - `effortLevel: medium` — balanced thinking budget
  - **Pre-tool-use hook** (Write/Edit/MultiEdit): stores a `git stash create` snapshot at `/tmp/ccw-baseline-<project>` before the first file edit, enabling manual rollback if needed
  - **Post-tool-use hook** (Write/Edit/MultiEdit): runs an external validation script after edits
  - **Permissions allowlist**: pre-approves read-only `git`, `gh`, and `jira` commands (status, diff, log, branch, pr, issue, search, etc.) plus `git add` and `git commit` so Claude never prompts for those

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
