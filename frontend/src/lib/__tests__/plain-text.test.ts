import { describe, expect, it } from "vitest";

import { htmlToPlainText, stripHtmlTags } from "@/lib/plain-text";

describe("stripHtmlTags (UAT M11-B08 — tytuły transkrypcji Fireflies)", () => {
  it("usuwa znaczniki i zwija odstępy", () => {
    expect(stripHtmlTags("<p>Rozmowa   rekrutacyjna</p>")).toBe("Rozmowa rekrutacyjna");
    expect(stripHtmlTags("<p>A</p><p>B</p>")).toBe("A B");
  });

  it("rozwija podstawowe encje i przepuszcza zwykły tekst", () => {
    expect(stripHtmlTags("R&amp;D &lt;test&gt;")).toBe("R&D <test>");
    expect(stripHtmlTags("Zwykły tytuł")).toBe("Zwykły tytuł");
    expect(stripHtmlTags(null)).toBe("");
  });
});

describe("stripHtmlTags — encje polskich znaków (UAT B09)", () => {
  it("rozwija nazwane encje polskich liter, także w treści bez znaczników", () => {
    expect(stripHtmlTags("nie analizował w og&oacute;le wąskich gardeł")).toBe(
      "nie analizował w ogóle wąskich gardeł",
    );
    expect(stripHtmlTags("Pracuje na dw&oacute;jce")).toBe("Pracuje na dwójce");
    expect(stripHtmlTags("&Lstrok;&oacute;d&zacute; &aogon;&eogon;&cacute;&nacute;&sacute;&zdot;")).toBe(
      "Łódź ąęćńśż",
    );
  });

  it("rozwija encje numeryczne dziesiętne i szesnastkowe", () => {
    expect(stripHtmlTags("og&#243;le i dw&#xF3;jka")).toBe("ogóle i dwójka");
  });

  it("nieznaną encję zostawia dosłownie, `&nbsp;` zwija do spacji", () => {
    expect(stripHtmlTags("A&nbsp;&nbsp;B &foo; C")).toBe("A B &foo; C");
  });
});

describe("htmlToPlainText — opis wydarzenia z Outlooka (retest 15.09.2026)", () => {
  const OUTLOOK_MAIL = `<html><head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<style type="text/css" style="display:none;"> P {margin-top:0;margin-bottom:0;} .MsoNormal {font-family:"Aptos";} </style>
</head>
<body dir="ltr">
<div class="elementToProof" style="font-family: Aptos, Arial; font-size: 12pt">
Dzień dobry,<br>
zapraszam na rozmowę w&nbsp;sprawie roli <b>Architekt IT</b>.</div>
<p class="MsoNormal">&nbsp;</p>
<p class="MsoNormal">&nbsp;</p>
<p>Pozdrawiam,<br>Anna Testowa</p>
<!-- [if mso]><style>.x{color:red}</style><![endif] -->
<script>alert(1)</script>
</body></html>`;

  it("dokument maila daje czysty tekst z akapitami, bez CSS z `<style>`", () => {
    const text = htmlToPlainText(OUTLOOK_MAIL);
    expect(text).toBe(
      "Dzień dobry,\nzapraszam na rozmowę w sprawie roli Architekt IT.\n\nPozdrawiam,\nAnna Testowa",
    );
    expect(text).not.toMatch(/<|margin|MsoNormal|Content-Type|alert/);
  });

  it("zwykły tekst wraca bez zmian, z zachowanymi liniami", () => {
    expect(htmlToPlainText("Linia 1\nLinia 2 <3")).toBe("Linia 1\nLinia 2 <3");
    expect(htmlToPlainText(null)).toBe("");
  });

  it("encje ze znacznikami są rozwijane po zdjęciu znaczników", () => {
    expect(htmlToPlainText("<p>R&amp;D &lt;b&gt; og&oacute;le</p>")).toBe("R&D <b> ogóle");
  });
});
