# Install `pw` from GitHub Releases

GitHub’s `…/releases/latest/download/install.sh` URL only resolves once the **current “Latest” GitHub Release** includes a file named **`install.sh`**. That file is uploaded by the **Release pw** workflow (not created automatically from a git tag).

## Install (recommended, after CI has published)

```bash
curl -LsSf "https://github.com/pkgwarden/pkgwarden_cli/releases/latest/download/install.sh" | sh
```

Wait for **Actions → Release pw** to finish on `pkgwarden/pkgwarden_cli` after a mirror or tag push. If you see **404** here, the release assets are not published yet (or “Latest” points at an empty release).

## Pin a version

```bash
curl -LsSf "https://github.com/pkgwarden/pkgwarden_cli/releases/download/pw-v0.1.0/install.sh" | sh
```

Use the same tag string as the GitHub Release (for example `pw-v0.1.0`).

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
