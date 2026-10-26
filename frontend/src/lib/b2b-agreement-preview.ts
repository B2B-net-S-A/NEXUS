// Podgląd umowy w Generatorze (B2B i zlecenie): odmiana nazwiska do
// narzędnika, styl ramki podglądu i wydruk. Wydzielone ze strony generatora
// 26.10.2026, żeby formularz umowy zlecenia nie importował całej strony.

/** Heurystyczna odmiana imienia i nazwiska do narzędnika („z Panem Janem
 * Kowalskim"). Best-effort — przy nietypowych/obcych nazwiskach pole jest
 * edytowalne. */
function titleCase(w: string): string {
  return w ? w.charAt(0).toUpperCase() + w.slice(1).toLowerCase() : w;
}

function declineInstrumentalToken(raw: string, gender: "m" | "k"): string {
  const w = titleCase(raw);
  const lw = w.toLowerCase();
  const cut = (n: number, suf: string) => w.slice(0, w.length - n) + suf;
  if (gender === "k") {
    if (lw.endsWith("ska") || lw.endsWith("cka") || lw.endsWith("dzka"))
      return cut(1, "ą");
    if (lw.endsWith("a")) return cut(1, "ą");
    return w; // nazwisko żeńskie zakończone spółgłoską — nieodmienne
  }
  if (lw.endsWith("ski") || lw.endsWith("cki") || lw.endsWith("dzki"))
    return cut(1, "im");
  if (lw.endsWith("y")) return cut(1, "ym");
  if (lw.endsWith("ek")) return cut(2, "kiem");
  if (lw.endsWith("eł")) return cut(2, "łem");
  if (lw.endsWith("k") || lw.endsWith("g")) return w + "iem";
  if (lw.endsWith("a")) return cut(1, "ą");
  if (
    lw.endsWith("o") ||
    lw.endsWith("i") ||
    lw.endsWith("e") ||
    lw.endsWith("u")
  )
    return w; // nieoczywiste zakończenie → zostaw (sprawdź ręcznie)
  return w + "em"; // typowa spółgłoska twarda
}

export function instrumentalPl(fullName: string, gender: "m" | "k"): string {
  const tokens = (fullName || "").trim().split(/\s+/).filter(Boolean);
  if (!tokens.length) return "";
  return tokens.map((t) => declineInstrumentalToken(t, gender)).join(" ");
}

export function printHtml(bodyHtml: string, title: string): void {
  const w = window.open("", "_blank", "width=820,height=1000");
  if (!w) return;
  w.document.write(
    `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${title}</title>` +
      "<style>body{font-family:Helvetica,Arial,sans-serif;max-width:780px;margin:24px auto;" +
      "line-height:1.55;color:#222;padding:0 20px}h1,h2,h3{color:#111}" +
      // §nagłówek nie zostaje sam na końcu strony (#4)
      "h1,h2,h3{break-after:avoid;page-break-after:avoid;break-inside:avoid}" +
      "table{border-collapse:collapse;width:100%;margin:1em 0}" +
      "th,td{border:1px solid #ccc;padding:6px 10px;text-align:left}" +
      "@media print{body{margin:0;padding:0}}</style>" +
      "<script>window.addEventListener('load',()=>setTimeout(()=>window.print(),300))</script>" +
      `</head><body>${bodyHtml}</body></html>`,
  );
  w.document.close();
}

export const PREVIEW_STYLE =
  "body{font-family:Helvetica,Arial,sans-serif;margin:18px;line-height:1.5;color:#222;font-size:13px}" +
  "h1{font-size:18px}h2{font-size:15px;margin-top:1.4em}h3{font-size:13px}" +
  "h1,h2,h3{break-after:avoid;page-break-after:avoid;break-inside:avoid}" +
  "table{border-collapse:collapse;width:100%;margin:1em 0}" +
  "th,td{border:1px solid #ccc;padding:5px 8px;text-align:left;vertical-align:top}";
