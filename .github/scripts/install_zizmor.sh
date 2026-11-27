#!/usr/bin/env bash
# Instalacja zizmora na runnerze (linux x86_64) z koła z PyPI, sprawdzonego
# sumą — jak Trivy w `ci.yml`, bez `pip install` z indeksu (przejęte wydanie
# z tą samą wersją nie przejdzie sumy). Koło to sam binarny plik w Ruście,
# bez zależności, więc wystarczy go rozpakować.
# Wersja i suma z https://pypi.org/pypi/zizmor/<wersja>/json (plik
# `zizmor-<wersja>-py3-none-manylinux_2_28_x86_64.whl`). Przy podbiciu wersji
# zmień OBIE wartości i pole `zizmor` w `.github/zizmor-baseline.json`.
set -euo pipefail

VERSION="1.33.1"
SHA256="49eb92a95347e7da58c3123e4d5b297dbb6fe8ecc328e9db68df14c08e25e151"
URL="https://files.pythonhosted.org/packages/49/bf/89961bcb9034e7c25af39f6e9d65d37eff9314b49034c2e2bb70ae42d818/zizmor-${VERSION}-py3-none-manylinux_2_28_x86_64.whl"

workdir="${RUNNER_TEMP:-/tmp}/zizmor-install"
mkdir -p "$workdir"
curl -fsSL --retry 6 --retry-delay 15 --retry-all-errors --connect-timeout 20 --max-time 120 \
  "$URL" -o "$workdir/zizmor.whl"
echo "${SHA256}  $workdir/zizmor.whl" | sha256sum -c -
python3 -m zipfile -e "$workdir/zizmor.whl" "$workdir/whl"
sudo install -m 0755 "$workdir/whl/zizmor-${VERSION}.data/scripts/zizmor" /usr/local/bin/zizmor
zizmor --version
