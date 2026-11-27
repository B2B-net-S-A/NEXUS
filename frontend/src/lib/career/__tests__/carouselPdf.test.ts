import { describe, expect, it } from "vitest";

import { jpegPagesToPdf } from "@/lib/career/carouselPdf";

const latin1 = (bytes: Uint8Array) => Array.from(bytes, (b) => String.fromCharCode(b)).join("");

describe("PDF karuzeli ze stron JPEG", () => {
  const jpeg = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3, 0xff, 0xd9]);
  const pdf = latin1(jpegPagesToPdf([1, 2, 3].map(() => ({ bytes: jpeg, width: 1080, height: 1350 }))));

  it("ma nagłówek, trzy strony w rozmiarze kadru i obrazy JPEG", () => {
    expect(pdf.startsWith("%PDF-1.4")).toBe(true);
    expect(pdf).toContain("/Count 3");
    expect(pdf.match(/\/Type \/Page /g)).toHaveLength(3);
    expect(pdf.match(/\/MediaBox \[0 0 1080 1350\]/g)).toHaveLength(3);
    expect(pdf.match(/\/Filter \/DCTDecode \/Length 9 /g)).toHaveLength(3);
    expect(pdf.trimEnd().endsWith("%%EOF")).toBe(true);
  });

  it("tabela xref wskazuje dokładnie początki obiektów", () => {
    const start = Number(/startxref\n(\d+)/.exec(pdf)![1]);
    expect(pdf.slice(start, start + 4)).toBe("xref");
    const rows = pdf.slice(start).split("\n").slice(3).filter((r) => / 00000 n $/.test(r));
    expect(rows).toHaveLength(2 + 3 * 3);
    rows.forEach((row, i) => {
      const offset = Number(row.slice(0, 10));
      expect(pdf.slice(offset).startsWith(`${i + 1} 0 obj`)).toBe(true);
    });
  });

  it("bez stron = błąd, nie pusty plik", () => {
    expect(() => jpegPagesToPdf([])).toThrow();
  });
});
