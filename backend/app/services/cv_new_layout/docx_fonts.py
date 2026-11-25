"""Krój Poppins osadzony w pliku Word „Nowego CV” (decyzja Artura z 25.11.2026).

Komputer klienta zwykle nie ma Poppinsa; bez osadzenia Word podstawia inny krój
i tabele stanowisk wyglądają inaczej niż w PDF. Osadzenie według ECMA-376 cz. 1,
§17.8.1: plik kroju jako część `/word/fonts/fontN.odttf`, pierwsze 32 bajty
zaciemnione kluczem z `w:fontKey` (GUID czytany od końca), wpis `w:embedRegular` /
`w:embedBold` w `fontTable.xml` i `w:embedTrueTypeFonts` w `settings.xml`.
Licencja OFL Poppinsa pozwala osadzać krój w dokumentach.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from docx.opc.constants import RELATIONSHIP_TYPE as RT
from lxml import etree
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn

OBFUSCATED_FONT = "application/vnd.openxmlformats-officedocument.obfuscatedFont"
# Elementy `w:settings`, które w schemacie stoją PRZED `w:embedTrueTypeFonts` —
# Word odrzuca plik z elementami w złej kolejności.
_SETTINGS_BEFORE = (
    "writeProtection",
    "view",
    "zoom",
    "removePersonalInformation",
    "removeDateAndTime",
    "doNotDisplayPageBoundaries",
    "displayBackgroundShape",
    "printPostScriptOverText",
    "printFractionalCharacterWidth",
    "printFormsData",
)


def obfuscate(font: bytes, key: str) -> bytes:
    """Zaciemnienie kroju (§17.8.1): 32 pierwsze bajty XOR bajtami GUID-u od końca.
    Ta sama operacja odwraca zaciemnienie."""
    digits = key.strip("{}").replace("-", "")
    guid = bytes.fromhex(digits)[::-1]
    head = bytes(b ^ guid[i % 16] for i, b in enumerate(font[:32]))
    return head + font[32:]


def _font_table(document: Any) -> Part:
    for rel in document.part.rels.values():
        if rel.reltype == RT.FONT_TABLE:
            return rel.target_part
    raise RuntimeError("Szablon Worda nie ma części fontTable.xml.")


def _enable_embedding(document: Any) -> None:
    settings = document.settings.element
    if settings.find(qn("w:embedTrueTypeFonts")) is not None:
        return
    flag = OxmlElement("w:embedTrueTypeFonts")
    before = {qn(f"w:{name}") for name in _SETTINGS_BEFORE}
    index = 0
    for i, child in enumerate(settings):
        if child.tag in before:
            index = i + 1
    settings.insert(index, flag)


def embed_font(document: Any, family: str, regular: Path, bold: Path) -> None:
    """Osadza krój `family` (zwykły i pogrubiony) w dokumencie python-docx."""
    table_part = _font_table(document)
    table = parse_xml(table_part.blob)
    font = next(
        (f for f in table.findall(qn("w:font")) if f.get(qn("w:name")) == family), None
    )
    if font is None:
        font = OxmlElement("w:font")
        font.set(qn("w:name"), family)
        table.append(font)
    for tag in ("w:embedRegular", "w:embedBold"):
        for old in font.findall(qn(tag)):
            font.remove(old)
    count = sum(
        1
        for p in document.part.package.iter_parts()
        if str(p.partname).startswith("/word/fonts/")
    )
    for tag, path in (("w:embedRegular", regular), ("w:embedBold", bold)):
        key = "{" + str(uuid.uuid4()).upper() + "}"
        count += 1
        part = Part(
            PackURI(f"/word/fonts/font{count}.odttf"),
            OBFUSCATED_FONT,
            obfuscate(path.read_bytes(), key),
            document.part.package,
        )
        rid = table_part.relate_to(part, RT.FONT)
        embed = OxmlElement(tag)
        embed.set(qn("r:id"), rid)
        embed.set(qn("w:fontKey"), key)
        font.append(embed)
    table_part._blob = etree.tostring(
        table, xml_declaration=True, encoding="UTF-8", standalone=True
    )
    _enable_embedding(document)
