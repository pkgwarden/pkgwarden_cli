# Install `pw` from GitHub Releases

## Install (recommended)

Install the latest release:

```bash
curl -LsSf "https://github.com/pkgwarden/pkgwarden_cli/releases/latest/download/install.sh" | sh
```

By default this installs `pw` into a user-writable directory and prints the next steps.

## Pin a version

```bash
curl -LsSf "https://github.com/pkgwarden/pkgwarden_cli/releases/download/pw-v0.1.0/install.sh" | sh
```

## Verify the install

```bash
pw --version
pw --help
```

## Uninstall

Remove the `pw` binary from wherever you installed it (commonly `~/.local/bin/pw`), then remove config if you want a clean slate:

```bash
rm -f ~/.local/bin/pw
rm -rf ~/.config/pkgwarden
```
