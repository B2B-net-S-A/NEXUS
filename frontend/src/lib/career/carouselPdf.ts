/**
 * PDF karuzeli na LinkedIn (post typu „dokument”) z gotowych stron JPEG —
 * jedna strona na slajd, obraz na całą stronę. Czysta funkcja bez zależności:
 * JPEG wchodzi do PDF-u bez dekodowania (`/DCTDecode`), więc nie potrzeba
 * biblioteki ani serwera. Slajdy rysuje trasa `grafika-posta?v=karuzela`.
 */

export interface PdfJpegPage {
  /** Plik JPEG (baseline albo progressive, RGB). */
  bytes: Uint8Array;
  /** Wymiary w pikselach = wymiary strony w punktach PDF. */
  width: number;
  height: number;
}

const enc = new TextEncoder();

export function jpegPagesToPdf(pages: readonly PdfJpegPage[]): Uint8Array {
  if (pages.length === 0) throw new Error("PDF bez stron");
  const chunks: Uint8Array[] = [];
  const offsets: number[] = [];
  let size = 0;
  const push = (part: string | Uint8Array) => {
    const bytes = typeof part === "string" ? enc.encode(part) : part;
    chunks.push(bytes);
    size += bytes.length;
  };
  const object = (id: number, body: string | (string | Uint8Array)[]) => {
    offsets[id] = size;
    push(`${id} 0 obj\n`);
    for (const part of Array.isArray(body) ? body : [body]) push(part);
    push("\nendobj\n");
  };

  // 1 katalog, 2 drzewo stron, dalej po trzy obiekty na stronę: strona, obraz, treść.
  const pageId = (i: number) => 3 + i * 3;
  const total = 2 + pages.length * 3;
  push("%PDF-1.4\n%âãÏÓ\n");
  object(1, "<< /Type /Catalog /Pages 2 0 R >>");
  object(2, `<< /Type /Pages /Kids [${pages.map((_, i) => `${pageId(i)} 0 R`).join(" ")}] /Count ${pages.length} >>`);
  pages.forEach((page, i) => {
    const id = pageId(i);
    const w = Math.round(page.width);
    const h = Math.round(page.height);
    object(
      id,
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${w} ${h}] /Resources << /XObject << /Im0 ${id + 1} 0 R >> >> /Contents ${id + 2} 0 R >>`,
    );
    object(id + 1, [
      `<< /Type /XObject /Subtype /Image /Width ${w} /Height ${h} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${page.bytes.length} >>\nstream\n`,
      page.bytes,
      "\nendstream",
    ]);
    const content = `q ${w} 0 0 ${h} 0 0 cm /Im0 Do Q`;
    object(id + 2, `<< /Length ${content.length} >>\nstream\n${content}\nendstream`);
  });

  const xref = size;
  const rows = ["0000000000 65535 f \n"];
  for (let id = 1; id <= total; id += 1) rows.push(`${String(offsets[id]).padStart(10, "0")} 00000 n \n`);
  push(`xref\n0 ${total + 1}\n${rows.join("")}`);
  push(`trailer\n<< /Size ${total + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`);

  const out = new Uint8Array(size);
  let at = 0;
  for (const c of chunks) {
    out.set(c, at);
    at += c.length;
  }
  return out;
}
