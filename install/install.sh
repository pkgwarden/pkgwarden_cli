#!/bin/sh
# Public installer: tape-only pw binary from GitHub Releases (see install/README.md).
set -eu

PKGWARDEN_GITHUB_REPO="${PKGWARDEN_GITHUB_REPO:-pkgwarden/pkgwarden_cli}"
TAG="${PKGWARDEN_VERSION:-__PW_RELEASE_TAG__}"

if [ "$TAG" = "__PW_RELEASE_TAG__" ]; then
  echo "Set PKGWARDEN_VERSION to a release tag (for example pw-v0.1.0), or use the" >&2
  echo "install.sh asset attached to that GitHub Release (it is pinned to the tag)." >&2
  exit 1
fi

norm_arch() {
  case "$(uname -m)" in
    x86_64|amd64) echo x86_64 ;;
    arm64|aarch64) echo aarch64 ;;
    *) echo "unsupported machine: $(uname -m)" >&2; exit 1 ;;
  esac
}

case "$(uname -s)" in
  Linux)
    TRIPLE="$(norm_arch)-unknown-linux-gnu"
    ;;
  Darwin)
    TRIPLE="$(norm_arch)-apple-darwin"
    ;;
  *)
    echo "unsupported OS: $(uname -s)" >&2
    exit 1
    ;;
esac

ASSET_NAME="pw-${TRIPLE}"
BASE_URL="https://github.com/${PKGWARDEN_GITHUB_REPO}/releases/download/${TAG}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

if command -v curl >/dev/null 2>&1; then
  curl -sSfL "${BASE_URL}/${ASSET_NAME}" -o "${TMP_DIR}/${ASSET_NAME}"
  curl -sSfL "${BASE_URL}/SHA256SUMS" -o "${TMP_DIR}/SHA256SUMS"
elif command -v wget >/dev/null 2>&1; then
  wget -q -O "${TMP_DIR}/${ASSET_NAME}" "${BASE_URL}/${ASSET_NAME}"
  wget -q -O "${TMP_DIR}/SHA256SUMS" "${BASE_URL}/SHA256SUMS"
else
  echo "install.sh: need curl or wget" >&2
  exit 1
fi

cd "$TMP_DIR"
if command -v sha256sum >/dev/null 2>&1; then
  grep -F "${ASSET_NAME}" SHA256SUMS | sha256sum -c -
elif command -v shasum >/dev/null 2>&1; then
  EXPECT="$(grep -F "${ASSET_NAME}" SHA256SUMS | awk '{print $1}')"
  test "$(shasum -a 256 "${ASSET_NAME}" | awk '{print $1}')" = "${EXPECT}"
else
  echo "install.sh: need sha256sum or shasum" >&2
  exit 1
fi

INSTALL_DIR="${PKGWARDEN_INSTALL_DIR:-$HOME/.local/bin}"
mkdir -p "${INSTALL_DIR}"
install -m755 "${TMP_DIR}/${ASSET_NAME}" "${INSTALL_DIR}/pw"
echo "Installed pw to ${INSTALL_DIR}/pw"
case ":${PATH}:" in
  *":${INSTALL_DIR}:"*) ;;
  *) echo "Add to PATH: export PATH=\"${INSTALL_DIR}:\$PATH\"" ;;
esac
