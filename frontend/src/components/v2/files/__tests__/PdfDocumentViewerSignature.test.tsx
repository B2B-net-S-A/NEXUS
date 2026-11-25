// @vitest-environment node
/**
 * Podpis w podglądzie PDF (zgłoszenie rekruterów 25.11.2026): podpisana umowa
 * przedwstępna wgrana do NEXUSA wyglądała w podglądzie na niepodpisaną, a ten
 * sam plik wysłany mailem miał podpis. Podpis elektroniczny (kwalifikowany,
 * zaufany, „Wypełnij i podpisz”) to adnotacja PDF — pole podpisu albo
 * pieczątka — a podgląd renderował strony z `AnnotationMode.DISABLE`.
 *
 * Test buduje PDF z podpisem w obu postaciach i pyta prawdziwy pdf.js, co
 * narysuje na stronie w trybie, którego używa `PdfDocumentViewer`.
 */
import { describe, expect, it } from "vitest";

import { viewerAnnotationMode } from "@/components/v2/files/PdfDocumentViewer";

/** Strona z tekstem, polem podpisu (/FT /Sig) i pieczątką z wyglądem „PODPIS”. */
function signedPdf(): Uint8Array {
  const enc = new TextEncoder();
  const stream = (dict: string, body: string) =>
    `<< ${dict} /Length ${body.length} >>\nstream\n${body}\nendstream`;
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R /AcroForm << /Fields [6 0 R] /SigFlags 3 >> >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] " +
      "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R /Annots [6 0 R 8 0 R] >>",
    stream("", "BT /F1 18 Tf 72 720 Td (Umowa przedwstepna) Tj ET"),
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    "<< /Type /Annot /Subtype /Widget /FT /Sig /T (Podpis1) /F 4 " +
      "/Rect [72 100 272 130] /P 3 0 R /AP << /N 7 0 R >> >>",
    stream(
      "/Type /XObject /Subtype /Form /BBox [0 0 200 30] /Resources << /Font << /F1 5 0 R >> >>",
      "BT /F1 14 Tf 5 10 Td (PODPIS) Tj ET",
    ),
    "<< /Type /Annot /Subtype /Stamp /F 4 /Rect [300 100 500 130] /AP << /N 7 0 R >> >>",
  ];
  let pdf = "%PDF-1.7\n";
  const offsets: number[] = [];
  objects.forEach((body, i) => {
    offsets.push(pdf.length);
    pdf += `${i + 1} 0 obj\n${body}\nendobj\n`;
  });
  const xref = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  pdf += offsets.map((o) => `${String(o).padStart(10, "0")} 00000 n \n`).join("");
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return enc.encode(pdf);
}

describe("PdfDocumentViewer: podpis elektroniczny", () => {
  it("rysuje na stronie pole podpisu i pieczątkę podpisu", async () => {
    const lib = await import("pdfjs-dist/legacy/build/pdf.mjs");
    const task = lib.getDocument({ data: signedPdf(), verbosity: 0 });
    const doc = await task.promise;
    const page = await doc.getPage(1);

    const drawn = async (mode: number) => {
      const ops = await page.getOperatorList({ annotationMode: mode });
      return ops.fnArray.filter((fn: number) => fn === lib.OPS.beginAnnotation).length;
    };

    // Kontrola, że plik testowy niesie podpis, który tryb bez adnotacji gubi.
    expect(await drawn(lib.AnnotationMode.DISABLE)).toBe(0);
    expect(await drawn(viewerAnnotationMode(lib))).toBe(2);
    await task.destroy();
  });
});
