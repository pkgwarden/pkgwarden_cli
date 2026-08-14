# Installing `pw` from GitHub Releases

Each release publishes a standalone `pw` binary per platform, a `SHA256SUMS` file, and an
`install.sh` pinned to that release.

## Install the latest release

```bash
curl -LsSf "https://github.com/pkgwarden/pkgwarden_cli/releases/latest/download/install.sh" | sh
```

## Pin a version

Use the tag string from the [releases page](https://github.com/pkgwarden/pkgwarden_cli/releases):

```bash
curl -LsSf "https://github.com/pkgwarden/pkgwarden_cli/releases/download/pw-vX.Y.Z/install.sh" | sh
```

## What the installer does

1. Detects your platform and picks the matching asset: `pw-x86_64-unknown-linux-gnu`,
   `pw-aarch64-unknown-linux-gnu`, `pw-x86_64-apple-darwin`, or `pw-aarch64-apple-darwin`.
   Linux and macOS are supported; there is no Windows build yet.
2. Downloads that asset and the release's `SHA256SUMS`, and verifies the checksum before
   installing. A mismatch aborts the install.
3. Installs the binary to `~/.local/bin/pw`, and tells you to add that directory to `PATH` if it
   is not already there.

Environment variables:

| Variable | Effect |
| --- | --- |
| `PKGWARDEN_INSTALL_DIR` | Install somewhere other than `~/.local/bin` |
| `PKGWARDEN_VERSION` | Release tag to install, when running a copy of `install.sh` that is not pinned to a release |
| `PKGWARDEN_GITHUB_REPO` | Source repository, for mirrors of the public releases |

## Verify the install

```bash
pw --version
pw --help
```

## Uninstall

Remove the binary, and the configuration directory if you want a clean slate:

```bash
rm -f ~/.local/bin/pw
rm -rf ~/.config/pkgwarden
```
