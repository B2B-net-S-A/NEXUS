// Odczyt i sprawdzenie paczki CRX3 (wtyczka dla polityki Chrome / Intune).
// Paczkę robi sam Chrome (`--pack-extension` w pack.sh); tu tylko sprawdzamy,
// że jest podpisana kluczem z pola `key` manifestu, ma to samo id i niesie ZIP.
//
// Format (components/crx_file/crx3.proto w Chromium):
//   "Cr24" | uint32 LE 3 | uint32 LE długość nagłówka | CrxFileHeader | ZIP
//   CrxFileHeader: 2 = sha256_with_rsa (AsymmetricKeyProof: 1 = klucz publiczny
//   DER, 2 = podpis), 10000 = signed_header_data (SignedData: 1 = crx_id, 16 B).
//   Podpis RSA-SHA256 obejmuje "CRX3 SignedData\0" | uint32 LE długość
//   signed_header_data | signed_header_data | ZIP.
import { createHash, createPublicKey, verify } from "node:crypto";

function readVarint(buf, pos) {
  let value = 0;
  let shift = 0;
  for (;;) {
    if (pos >= buf.length) throw new Error("CRX: ucięty varint");
    const byte = buf[pos++];
    value += (byte & 0x7f) * 2 ** shift;
    if (!(byte & 0x80)) return [value, pos];
    shift += 7;
  }
}

/** Pola protobuf długości zmiennej (typ 2) jako [numer pola, bajty]. */
function lengthDelimitedFields(buf) {
  const fields = [];
  let pos = 0;
  while (pos < buf.length) {
    let tag;
    [tag, pos] = readVarint(buf, pos);
    const wireType = tag & 7;
    const field = Math.floor(tag / 8);
    if (wireType === 0) {
      [, pos] = readVarint(buf, pos);
    } else if (wireType === 2) {
      let len;
      [len, pos] = readVarint(buf, pos);
      if (pos + len > buf.length) throw new Error("CRX: ucięte pole nagłówka");
      fields.push([field, buf.subarray(pos, pos + len)]);
      pos += len;
    } else {
      throw new Error(`CRX: nieobsługiwany typ pola ${wireType}`);
    }
  }
  return fields;
}

/** Id wtyczki z klucza publicznego DER: pierwsze 16 B SHA-256, cyfry hex → a–p. */
export function extensionIdFromPublicKey(der) {
  const hex = createHash("sha256").update(der).digest("hex").slice(0, 32);
  return [...hex].map((c) => String.fromCharCode(97 + parseInt(c, 16))).join("");
}

/**
 * Rozbiera CRX3 i sprawdza podpis. Zwraca id, klucz publiczny (base64, jak pole
 * `key` w manifeście) i bajty ZIP-a. Rzuca błąd, gdy paczka jest uszkodzona,
 * nie ma podpisu RSA pasującego do crx_id albo podpis się nie zgadza.
 */
export function readCrx3(buf) {
  if (buf.length < 12 || buf.toString("latin1", 0, 4) !== "Cr24") throw new Error("CRX: brak nagłówka Cr24");
  if (buf.readUInt32LE(4) !== 3) throw new Error(`CRX: wersja ${buf.readUInt32LE(4)}, oczekiwana 3`);
  const headerLen = buf.readUInt32LE(8);
  if (12 + headerLen > buf.length) throw new Error("CRX: ucięty nagłówek");
  const header = buf.subarray(12, 12 + headerLen);
  const zip = buf.subarray(12 + headerLen);

  const fields = lengthDelimitedFields(header);
  const signedHeaderData = fields.find(([f]) => f === 10000)?.[1];
  if (!signedHeaderData) throw new Error("CRX: brak signed_header_data");
  const crxId = lengthDelimitedFields(signedHeaderData).find(([f]) => f === 1)?.[1];
  if (!crxId || crxId.length !== 16) throw new Error("CRX: brak crx_id");

  const proofs = fields
    .filter(([f]) => f === 2)
    .map(([, proof]) => {
      const parts = lengthDelimitedFields(proof);
      return { publicKey: parts.find(([f]) => f === 1)?.[1], signature: parts.find(([f]) => f === 2)?.[1] };
    })
    .filter((p) => p.publicKey && p.signature);
  // Chrome wymaga podpisu kluczem, z którego wynika crx_id (to on daje id wtyczki).
  const own = proofs.find((p) => createHash("sha256").update(p.publicKey).digest().subarray(0, 16).equals(crxId));
  if (!own) throw new Error("CRX: brak podpisu RSA kluczem zgodnym z crx_id");

  const sizeLE = Buffer.alloc(4);
  sizeLE.writeUInt32LE(signedHeaderData.length);
  const signed = Buffer.concat([Buffer.from("CRX3 SignedData\0", "latin1"), sizeLE, signedHeaderData, zip]);
  const key = createPublicKey({ key: own.publicKey, format: "der", type: "spki" });
  if (!verify("sha256", signed, key, own.signature)) throw new Error("CRX: podpis się nie zgadza");

  return { id: extensionIdFromPublicKey(own.publicKey), publicKey: own.publicKey.toString("base64"), zip };
}

// node scripts/crx3.mjs <plik.crx> <oczekiwane id> — sprawdzenie w pack.sh.
if (process.argv[1] && import.meta.url === new URL(`file://${process.argv[1]}`).href) {
  const { readFileSync } = await import("node:fs");
  const [file, expectedId] = process.argv.slice(2);
  const crx = readCrx3(readFileSync(file));
  if (expectedId && crx.id !== expectedId) {
    console.error(`CRX: id ${crx.id}, oczekiwane ${expectedId}`);
    process.exit(1);
  }
  console.log(`CRX3 OK: id ${crx.id}, ZIP ${crx.zip.length} B`);
}
