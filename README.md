# pkgwarden CLI (`pw`)

Install `pw`, connect it to your pkgwarden deployment, and use it to sync and manage dependencies with pkgwarden’s approval workflow.

## Install

Install the prebuilt `pw` binary from GitHub Releases:

```bash
curl -LsSf "https://github.com/pkgwarden/pkgwarden_cli/releases/latest/download/install.sh" | sh
```

Then verify it works:

```bash
pw --help
```

More options (pin a version, choose install dir, uninstall) are in [install/README.md](install/README.md).

## Quickstart

Initialize config in your project:

```bash
pw init
```

Log in with a token (the command stores it locally in `~/.config/pkgwarden/credentials.toml`):

```bash
pw login --api-url https://<your-host>/api/v1 --token "$TOKEN" --type tape
```

Sync dependencies using your existing package manager (uv / pip / poetry / npm / pnpm / yarn):

```bash
pw sync
```

## Common commands

- `pw status` — show current config + token sources
- `pw doctor` — connectivity and configuration checks
- `pw sync` — install/sync dependencies via your package manager
- `pw add <pkg> [--version X]` — add a dependency via your package manager
- `pw why-blocked <name>==<version>` — explain why a version is blocked

## Configuration precedence

- CLI flags (like `--api-url`) win.
- Environment variables override project config.
- Project config is stored in `.pkgwarden.toml`.
