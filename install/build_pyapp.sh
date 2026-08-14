#!/usr/bin/env bash
# Build a standalone `pw` binary via PyApp (https://github.com/ofek/pyapp).
# Usage: build_pyapp.sh <gate|enterprise> <output_pw_binary_path>
# Run from monorepo pkgwarden-cli/ or from a standalone clone whose root is the package.
set -euo pipefail

MODE="${1:?first arg: gate or enterprise}"
OUT_PATH="${2:?second arg: output path for pw binary}"
if [[ "${OUT_PATH}" != /* ]]; then
  OUT_PATH="$(pwd)/${OUT_PATH#./}"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYAPP_TAG="v0.29.0"
PYAPP_URL="https://github.com/ofek/pyapp/releases/download/${PYAPP_TAG}/source.tar.gz"

cd "${CLI_ROOT}"
export PYAPP_PROJECT_VERSION="$(
  uv run python -c "import tomllib, pathlib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])"
)"
uv build -q
REPO_ROOT="$(cd "${CLI_ROOT}/.." && pwd)"
CORE_WHL="$(uv run --with packaging python "${REPO_ROOT}/scripts/select_latest_wheel.py" dist 'pkgwarden_cli-*.whl' pkgwarden_cli)"
if [[ ! -f "${CORE_WHL}" ]]; then
  echo "missing core wheel under ${CLI_ROOT}/dist" >&2
  exit 1
fi

WORKDIR="$(mktemp -d)"
cleanup() {
  rm -rf "${WORKDIR}"
}
trap cleanup EXIT

curl -sSfL "${PYAPP_URL}" -o "${WORKDIR}/pyapp.tgz"
tar -xzf "${WORKDIR}/pyapp.tgz" -C "${WORKDIR}"
PYAPP_SRC="${WORKDIR}/pyapp-${PYAPP_TAG}"
cd "${PYAPP_SRC}"

export PYAPP_EXEC_SPEC="pkgwarden_cli.main:main"
export PYAPP_PROJECT_NAME="pw"
export PYAPP_PYTHON_VERSION="3.13"

if [[ "${MODE}" == "gate" ]]; then
  unset PYAPP_PROJECT_DEPENDENCY_FILE PYAPP_DISTRIBUTION_EMBED PYAPP_FULL_ISOLATION 2>/dev/null || true
  export PYAPP_PROJECT_PATH="${CORE_WHL}"
elif [[ "${MODE}" == "enterprise" ]]; then
  unset PYAPP_PROJECT_PATH PYAPP_PROJECT_DEPENDENCY_FILE 2>/dev/null || true
  ENT_ROOT="$(cd "${CLI_ROOT}/../pkgwarden-cli-enterprise" && pwd)"
  if [[ ! -d "${ENT_ROOT}" ]]; then
    echo "enterprise mode requires ../pkgwarden-cli-enterprise next to ${CLI_ROOT}" >&2
    exit 1
  fi
  cd "${ENT_ROOT}"
  uv build -q
  ENT_WHL="$(uv run --with packaging python "${REPO_ROOT}/scripts/select_latest_wheel.py" dist 'pkgwarden_cli_enterprise-*.whl' pkgwarden_cli_enterprise)"
  if [[ ! -f "${ENT_WHL}" ]]; then
    echo "missing enterprise wheel under ${ENT_ROOT}/dist" >&2
    exit 1
  fi
  detect_host_triple() {
    if [[ -n "${PYAPP_HOST_TRIPLE:-}" ]]; then
      echo "${PYAPP_HOST_TRIPLE}"
      return
    fi
    local os arch
    os="$(uname -s)"
    arch="$(uname -m)"
    case "${os}-${arch}" in
      Linux-x86_64) echo "x86_64-unknown-linux-gnu" ;;
      Linux-aarch64 | Linux-arm64) echo "aarch64-unknown-linux-gnu" ;;
      Darwin-x86_64) echo "x86_64-apple-darwin" ;;
      Darwin-arm64) echo "aarch64-apple-darwin" ;;
      *)
        echo "unsupported host for enterprise PyApp build: ${os} ${arch}" >&2
        exit 1
        ;;
    esac
  }
  HOST_TRIPLE="$(detect_host_triple)"
  PREBUILT_DIST="${WORKDIR}/enterprise-python.tar.gz"
  LAYOUT_LINES="$(
    uv run python "${REPO_ROOT}/scripts/prepare_pyapp_enterprise_distribution.py" \
      --triple "${HOST_TRIPLE}" \
      --core-wheel "${CORE_WHL}" \
      --enterprise-wheel "${ENT_WHL}" \
      --output "${PREBUILT_DIST}"
  )"
  PYTHON_PATH="$(echo "${LAYOUT_LINES}" | tail -2 | sed -n '1p')"
  SITE_PACKAGES_PATH="$(echo "${LAYOUT_LINES}" | tail -1)"
  cd "${PYAPP_SRC}"
  export PYAPP_DISTRIBUTION_PATH="${PREBUILT_DIST}"
  export PYAPP_DISTRIBUTION_PYTHON_PATH="${PYTHON_PATH}"
  export PYAPP_DISTRIBUTION_SITE_PACKAGES_PATH="${SITE_PACKAGES_PATH}"
  export PYAPP_DISTRIBUTION_PIP_AVAILABLE="1"
  export PYAPP_SKIP_INSTALL="1"
  export PYAPP_FULL_ISOLATION="1"
else
  echo "mode must be gate or enterprise, got: ${MODE}" >&2
  exit 1
fi

cargo build --release
pyapp_bin="target/release/pyapp"
if [[ ! -f "${pyapp_bin}" ]]; then
  echo "missing ${pyapp_bin}; listing target/release:" >&2
  ls -la target/release >&2 || true
  exit 1
fi
cp -f "${pyapp_bin}" "${OUT_PATH}"
chmod a+x "${OUT_PATH}"
if [[ ! -x "${OUT_PATH}" ]]; then
  echo "binary missing or not executable after copy: ${OUT_PATH}" >&2
  ls -la "$(dirname "${OUT_PATH}")" >&2 || true
  exit 1
fi
