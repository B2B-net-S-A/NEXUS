"""Kompiluje reguły Peppol BIS Billing 3 (Schematron) do XSLT w ``app/services/peppol/rules``.

Źródła (przypięte wersje i SHA-256, bo reguły decydują, czy e-faktura wyjdzie):

* ``CEN-EN16931-UBL.sch`` i ``PEPPOL-EN16931-UBL.sch`` z repozytorium
  OpenPEPPOL/peppol-bis-invoice-3, wydanie 3.0.21 (pierwszy plik na licencji
  EUPL 1.2, drugi zawiera reguły CEN za zgodą CEN — nagłówki plików),
* kompilator SchXslt 1.10.1 (Maven Central, licencja MIT), krok
  ``pipeline-for-svrl.xsl`` (include → expand → compile, wynik SVRL).

Nowe wydanie Peppol (maj i listopad) = zmiana ``RELEASE`` i sum, uruchomienie
skryptu, testy ``tests/test_peppol_ubl.py`` i commit wygenerowanych plików.

Uruchomienie (z ``backend/``, potrzebny pakiet ``saxonche``):

    python3 scripts/build_peppol_rules.py
"""

from __future__ import annotations

import hashlib
import io
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

RELEASE = "3.0.21"
SCHXSLT = "1.10.1"
SOURCES = {
    "CEN-EN16931-UBL.sch": "268d4f7a2688676695e6c69cba6fba69a6802604fee12cb544a6b30ff09555a3",
    "PEPPOL-EN16931-UBL.sch": "9616cfffb418f349b532c1e25d3c831b8af6a47f4f5607ca0df4b1336f48e5f3",
}
SCHXSLT_SHA256 = "4f4f21edab7b37f96ad59ae12a344d3510f1092ac46b6d81a4efa0120b73cb58"
SCH_URL = "https://raw.githubusercontent.com/OpenPEPPOL/peppol-bis-invoice-3/{release}/rules/sch/{name}"
SCHXSLT_URL = "https://repo1.maven.org/maven2/name/dmaus/schxslt/schxslt/{version}/schxslt-{version}.jar"
TARGET = Path(__file__).resolve().parents[1] / "app" / "services" / "peppol" / "rules"


def _fetch(url: str, sha256: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 — stały adres https
        content = response.read()
    digest = hashlib.sha256(content).hexdigest()
    if digest != sha256:
        raise SystemExit(f"Suma SHA-256 się nie zgadza: {url} ({digest})")
    return content


def main() -> int:
    from saxonche import PySaxonProcessor

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        jar = _fetch(SCHXSLT_URL.format(version=SCHXSLT), SCHXSLT_SHA256)
        zipfile.ZipFile(io.BytesIO(jar)).extractall(work / "schxslt")
        pipeline = work / "schxslt" / "xslt" / "2.0" / "pipeline-for-svrl.xsl"
        TARGET.mkdir(parents=True, exist_ok=True)
        with PySaxonProcessor(license=False) as processor:
            compiler = processor.new_xslt30_processor()
            executable = compiler.compile_stylesheet(stylesheet_file=str(pipeline))
            for name, sha256 in SOURCES.items():
                source = work / name
                source.write_bytes(
                    _fetch(SCH_URL.format(release=RELEASE, name=name), sha256)
                )
                output = TARGET / name.replace(".sch", ".xsl")
                executable.transform_to_file(
                    source_file=str(source), output_file=str(output)
                )
                print(
                    f"{output.relative_to(TARGET.parents[3])}: {output.stat().st_size} B"
                )
    return 0


if __name__ == "__main__":
    sys.exit(main())
