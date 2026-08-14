# pkgwarden CLI (`pw`)

Install `pw`, connect it to your pkgwarden deployment, and use it to sync and manage dependencies with pkgwarden’s approval workflow.

## Install

The URL `…/releases/latest/download/install.sh` only works after GitHub has a **published Release** that includes an `install.sh` **asset** (tags alone are not enough). After each mirror, the **Release pw** workflow on `pkgwarden/pkgwarden_cli` builds the binaries and uploads `install.sh` plus `SHA256SUMS`—wait for that run to finish before using `latest`.

**Latest installer (after Release pw has succeeded at least once):**

```bash
curl -LsSf "https://github.com/pkgwarden/pkgwarden_cli/releases/latest/download/install.sh" | sh
```

**Pinned release (replace the tag with the one you ship, e.g. `pw-v0.1.0`):**

```bash
curl -LsSf "https://github.com/pkgwarden/pkgwarden_cli/releases/download/pw-v0.1.0/install.sh" | sh
```

If `latest` returns **404**, check **Actions → Release pw** on `pkgwarden/pkgwarden_cli`. If GitHub shows a **Latest** release with no assets, delete that empty release (or run **Release pw** manually for your tag) so `latest` points at a release that includes `install.sh`.

Then verify:

```bash
pw --help
```

More options (install dir, uninstall) are in [install/README.md](install/README.md).

## Quickstart

Initialize config in your project:

```bash
pw init
```

Log in with a token (the command stores it locally in `~/.config/pkgwarden/credentials.toml`):

```bash
pw login --api-url https://<your-host>/api/v1 --token "$TOKEN" --type gate
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
- `pw why-blocked <name>==<version>` — explain why a version is blocked (including `allowed_by_exception` when a CVE exception applies)
- `pw ci setup` — write registry credentials + env for a CI runner (see below)

## CI runners

`pw ci setup` persists what later CI steps need to install through pkgwarden, instead of
authenticating a single child process the way `pw sync` does. Run it once before your
install steps:

```bash
export PKGWARDEN_API_URL=https://index.pkgwarden.com/api/v1
export PKGWARDEN_MODE=gate
export PKGWARDEN_GATE_TOKEN=***
pw ci setup
```

It detects every package manager in the working directory and writes a `0600` netrc and an
npmrc (under `$RUNNER_TEMP` when set, else `~/.config/pkgwarden/ci/`). On GitHub Actions it
appends `NETRC`, `UV_DEFAULT_INDEX`, `PIP_INDEX_URL`, `NPM_CONFIG_USERCONFIG` (plus
`YARN_NPM_REGISTRY_SERVER` for yarn classic) to `$GITHUB_ENV`; elsewhere it prints
`export KEY=VALUE` lines on stdout, so `eval "$(pw ci setup)"` works. The token is never
printed.

Poetry and Yarn Berry are not configured automatically — set the index in `pyproject.toml`
or `npmRegistryServer` in `.yarnrc.yml` yourself.

## Configuration precedence

- CLI flags (like `--api-url`) win.
- Environment variables override project config.
- Project config is stored in `.pkgwarden.toml`.

Because enterprise command *source* lives in a separate repo/package,
anyone can audit what ships to gate users (this wheel) without seeing the
enterprise-only code paths.

## Further reading (monorepo)

- [PW_CLI_COMMAND_BOUNDARY.md](../docs/PW_CLI_COMMAND_BOUNDARY.md) — which commands live in core vs enterprise
- [PW_CLI_PLUGIN_INTERFACE.md](../docs/PW_CLI_PLUGIN_INTERFACE.md) — entry points and hooks
- [PW_CLI_MIGRATION.md](../docs/PW_CLI_MIGRATION.md) — migration and release pipelines
