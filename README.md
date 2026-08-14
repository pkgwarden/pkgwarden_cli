# pkgwarden CLI (`pw`)

`pw` is the command-line client for [pkgwarden](https://pkgwarden.com). It routes installs from
your existing package manager (uv, pip, poetry, npm, pnpm, yarn) through your pkgwarden gate: an
index that only serves package versions your policy allows, so unapproved versions never reach
your machines. When an install fails because a version is blocked, `pw why-blocked` tells you
which vulnerability caused it, instead of leaving you with an opaque resolver error.

The same binary works on developer laptops and CI runners.

## Install

Install the latest release:

```bash
curl -LsSf "https://github.com/pkgwarden/pkgwarden_cli/releases/latest/download/install.sh" | sh
```

Pin a specific release by tag (replace `pw-vX.Y.Z` with a tag from the
[releases page](https://github.com/pkgwarden/pkgwarden_cli/releases)):

```bash
curl -LsSf "https://github.com/pkgwarden/pkgwarden_cli/releases/download/pw-vX.Y.Z/install.sh" | sh
```

The installer downloads the binary for your platform, verifies it against the release's
`SHA256SUMS`, and installs it to `~/.local/bin/pw` (override with `PKGWARDEN_INSTALL_DIR`).

To install manually, download the asset for your platform from the
[releases page](https://github.com/pkgwarden/pkgwarden_cli/releases) and verify it yourself:

```bash
TAG=pw-vX.Y.Z
ASSET=pw-aarch64-apple-darwin   # or pw-x86_64-apple-darwin, pw-{x86_64,aarch64}-unknown-linux-gnu
BASE="https://github.com/pkgwarden/pkgwarden_cli/releases/download/$TAG"

curl -LsSfO "$BASE/$ASSET"
curl -LsSfO "$BASE/SHA256SUMS"
grep -F "$ASSET" SHA256SUMS | shasum -a 256 -c -   # sha256sum -c - on Linux

install -m755 "$ASSET" ~/.local/bin/pw
```

Confirm the install:

```bash
pw --version
pw --help
```

More options, including uninstall, are in [install/README.md](install/README.md).

## Quickstart

Create `.pkgwarden.toml` for your project (interactive; add `--yes` to accept the detected
defaults):

```bash
pw init
```

Store your token. It is written to `~/.config/pkgwarden/credentials.toml` with owner-only
permissions and is never printed back:

```bash
pw login --api-url https://<your-host>/api/v1 --token "$TOKEN" --type gate
```

Check that the deployment is reachable and your token resolves:

```bash
pw doctor
```

Install dependencies through the gate, using whichever package manager the project already uses:

```bash
pw sync
```

## Common commands

- `pw status`: show the resolved config and where each token comes from
- `pw doctor`: connectivity, token, and deployment health checks
- `pw sync`: install project dependencies through the gate
- `pw add <package>`: add a dependency; a blocked version points you at `pw why-blocked`
- `pw remove <package>` / `pw lock`: remove a dependency, or refresh the lockfile against the gate
- `pw why-blocked <name>==<version>`: explain why a version is blocked, including when a CVE
  exception already allows it
- `pw resolution-insights <name>`: show which versions of a package the gate index can serve
- `pw exception`: create, list, and revoke CVE exceptions
- `pw vscode`: VS Code extension allowlist tools
- `pw ci setup`: configure a CI runner (below)

Run `pw <command> --help` for the full option list.

## CI runners

`pw ci setup` persists what later CI steps need in order to install through pkgwarden, rather
than authenticating a single child process the way `pw sync` does. Run it once before your
install steps:

```bash
export PKGWARDEN_API_URL=https://index.pkgwarden.com/api/v1
export PKGWARDEN_MODE=gate
export PKGWARDEN_GATE_TOKEN=***
pw ci setup
```

It detects every package manager in the working directory and writes a `0600` netrc plus an
npmrc (under `$RUNNER_TEMP` when set, otherwise `~/.config/pkgwarden/ci/`). On GitHub Actions it
appends `NETRC`, `UV_DEFAULT_INDEX`, `PIP_INDEX_URL`, `NPM_CONFIG_USERCONFIG` (plus
`YARN_NPM_REGISTRY_SERVER` for yarn classic) to `$GITHUB_ENV`. Elsewhere it prints
`export KEY=VALUE` lines on stdout, so `eval "$(pw ci setup)"` works. The token is never printed.

Poetry and Yarn Berry are not configured automatically: set the index in `pyproject.toml` or
`npmRegistryServer` in `.yarnrc.yml` yourself.

## Configuration

Settings resolve in this order, first match wins:

1. Command-line flags such as `--api-url`
2. Environment variables such as `PKGWARDEN_API_URL` and `PKGWARDEN_GATE_TOKEN`
3. Project config in `.pkgwarden.toml` (found by walking up from the working directory)

Tokens live in `~/.config/pkgwarden/credentials.toml`, keyed by deployment, and are never stored
in the project config.

## About this repository

This is an automatically published mirror of the pkgwarden CLI source. The source of truth is an
internal repository, so **pull requests here cannot be merged**. Bug reports and feature requests
are welcome as issues, and we track them internally.

Commands for pkgwarden's enterprise and airgapped deployments ship as a separate plugin package
that is not published here. Keeping them out of this repository means anyone can audit exactly
what gate users run.

Please do not report security vulnerabilities in public issues. See [SECURITY.md](SECURITY.md).

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
