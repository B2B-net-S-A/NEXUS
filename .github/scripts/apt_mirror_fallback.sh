#!/usr/bin/env bash
# Zapasowe mirrory Ubuntu dla apt na runnerze GitHuba.
#
# 11.11.2026 runnery przez ponad godzinę nie rozwiązywały nazw *.ubuntu.com
# („Temporary failure resolving 'security.ubuntu.com'”), choć inne hosty
# (packages.microsoft.com, npm) działały. apt-get w kroku OCR padał i grupy
# wypadały z kolejki merge'ów (runy 43036754528, 43039695288, 43046213568);
# same ponowienia nie pomagały, bo awaria trwała dłużej niż one.
#
# Runner bierze źródła z /etc/apt/apt-mirrors.txt (mirror+file). Gdy
# archive.ubuntu.com się nie rozwiązuje (albo z --force, po nieudanej próbie
# apt-get), lista dostaje mirrory spoza ubuntu.com. Podpis InRelease apt
# sprawdza kluczem Ubuntu, więc mirror nie musi być zaufany.
set -euo pipefail

list=/etc/apt/apt-mirrors.txt
if [ ! -f "$list" ]; then
  echo "Brak $list — źródła apt zostają bez zmian."
  exit 0
fi
if grep -q "mirrors.edge.kernel.org" "$list"; then
  exit 0
fi
if [ "${1:-}" != "--force" ] && getent hosts archive.ubuntu.com >/dev/null; then
  exit 0
fi

echo "::warning::Mirrory Ubuntu niedostępne z runnera — apt korzysta z zapasowych (kernel.org, RWTH Aachen)."
printf '%s\n' \
  "http://mirrors.edge.kernel.org/ubuntu/" \
  "http://ftp.halifax.rwth-aachen.de/ubuntu/" \
  | sudo tee "$list" >/dev/null
