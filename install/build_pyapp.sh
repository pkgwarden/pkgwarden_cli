#!/usr/bin/env bash
# Build a standalone `pw` binary via PyApp (https://github.com/ofek/pyapp).
# Usage: build_pyapp.sh <tape|enterprise> <output_pw_binary_path>
# Run from monorepo pkgwarden-cli/ or from a standalone clone whose root is the package.
set -euo pipefail

MODE="${1:?first arg: tape or enterprise}"
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
CORE_WHL="$(echo "${CLI_ROOT}"/dist/pkgwarden_cli-*.whl | awk '{print $1}')"
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

if [[ "${MODE}" == "tape" ]]; then
  unset PYAPP_PROJECT_DEPENDENCY_FILE PYAPP_DISTRIBUTION_EMBED PYAPP_FULL_ISOLATION 2>/dev/null || true
  export PYAPP_PROJECT_PATH="${CORE_WHL}"
elif [[ "${MODE}" == "enterprise" ]]; then
  unset PYAPP_PROJECT_PATH 2>/dev/null || true
  ENT_ROOT="$(cd "${CLI_ROOT}/../pkgwarden-cli-enterprise" && pwd)"
  if [[ ! -d "${ENT_ROOT}" ]]; then
    echo "enterprise mode requires ../pkgwarden-cli-enterprise next to ${CLI_ROOT}" >&2
    exit 1
  fi
  cd "${ENT_ROOT}"
  uv build -q
  ENT_WHL="$(echo "${ENT_ROOT}"/dist/pkgwarden_cli_enterprise-*.whl | awk '{print $1}')"
  if [[ ! -f "${ENT_WHL}" ]]; then
    echo "missing enterprise wheel under ${ENT_ROOT}/dist" >&2
    exit 1
  fi
  cd "${PYAPP_SRC}"
  # PyApp first-run pip resolves these paths; they must survive WORKDIR cleanup (trap EXIT).
  enterprise_req="${WORKDIR}/enterprise-requirements.txt"
  {
    echo "${CORE_WHL}"
    echo "${ENT_WHL}"
  } >"${enterprise_req}"
  export PYAPP_PROJECT_DEPENDENCY_FILE="${enterprise_req}"
  export PYAPP_DISTRIBUTION_EMBED="1"
  export PYAPP_FULL_ISOLATION="1"
else
  echo "mode must be tape or enterprise, got: ${MODE}" >&2
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
