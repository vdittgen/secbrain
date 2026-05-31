#!/usr/bin/env bash
# Fetch a relocatable Python runtime into python_runtime/.
# This runtime is bundled into SecBrain.app/Contents/Resources/python_runtime/
# and used at first launch to create ~/.secbrain/venv/ + pip-install deps.
#
# Source: https://github.com/astral-sh/python-build-standalone
# Maintainer: Astral (uv, ruff). Reputable, widely used for embedded Python.

set -euo pipefail

VERSION_DATE="20250115"
PY_VERSION="3.11.11"
DEST="python_runtime"

# --- Detect host OS + architecture and map to a python-build-standalone triple ---
uname_s="$(uname -s)"
uname_m="$(uname -m)"

case "${uname_m}" in
  arm64 | aarch64) ARCH="aarch64" ;;
  x86_64 | amd64)  ARCH="x86_64" ;;
  *) echo "Unsupported architecture: ${uname_m}" >&2; exit 1 ;;
esac

case "${uname_s}" in
  Darwin) PLATFORM="apple-darwin" ;;
  Linux)  PLATFORM="unknown-linux-gnu" ;;
  MINGW* | MSYS* | CYGWIN*)
    PLATFORM="pc-windows-msvc"
    if [ "${ARCH}" != "x86_64" ]; then
      echo "Only x86_64 Windows builds are published by python-build-standalone." >&2
      exit 1
    fi
    ;;
  *) echo "Unsupported OS: ${uname_s}" >&2; exit 1 ;;
esac

TRIPLE="${ARCH}-${PLATFORM}"

# The interpreter lands at a different path on Windows vs. Unix.
if [ "${PLATFORM}" = "pc-windows-msvc" ]; then
  PY_BIN="${DEST}/python/python.exe"
else
  PY_BIN="${DEST}/python/bin/python3"
fi

URL="https://github.com/astral-sh/python-build-standalone/releases/download/${VERSION_DATE}/cpython-${PY_VERSION}+${VERSION_DATE}-${TRIPLE}-install_only.tar.gz"

if [ -x "${PY_BIN}" ]; then
  echo "✓ python_runtime/ already present (${TRIPLE}). Skipping fetch."
  "${PY_BIN}" --version
  exit 0
fi

mkdir -p "${DEST}"
echo "Fetching ${URL}"
curl -fsSL -o "${DEST}/pbs.tar.gz" "${URL}"

echo "Extracting…"
tar -xzf "${DEST}/pbs.tar.gz" -C "${DEST}"
rm "${DEST}/pbs.tar.gz"

echo "✓ Python runtime installed at ${DEST}/python/ (${TRIPLE})"
"${PY_BIN}" --version
