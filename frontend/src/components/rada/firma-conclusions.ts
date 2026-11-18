// Wnioski opisowe zakładki „Firma” Rady (R7). Uwaga Rady z 18.11.2026:
// „wnioski — opisowo; lejek może być zwinięty, bo wnioski powinny się też
// odnosić do lejka”. Reguły na liczbach z NEXUSA, bez modelu: zdanie ma się
// dać sprawdzić z tabelą obok.

import type { BoardPeople } from "@/lib/api/supervisory-board";

/** Powody, w których decyzja wyszła od konsultanta. */
const CONSULTANT_REASONS = new Set(["consultant_resigned", "better_offer", "personal_reasons"]);
/** Powody po stronie klienta (projekt, budżet, przejęcie). */
const CLIENT_REASONS = new Set(["project_ended", "client_budget_cut", "poached_by_client"]);

function plural(n: number, one: string, few: string, many: string): string {
  if (n === 1) return one;
  const last = n % 10;
  const lastTwo = n % 100;
  return last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14) ? few : many;
}

function change(current: number, previous: number): string {
  const diff = current - previous;
  if (diff === 0) return "tyle samo co w poprzednim okresie";
  return `${diff > 0 ? "o " + diff + " więcej" : "o " + -diff + " mniej"} niż w poprzednim okresie (${previous})`;
}

export function firmaConclusions(data: BoardPeople, funnelSentence: string | null): string[] {
  const out: string[] = [];
  const { placements, contractors, flows, exits } = data;

  const topPlacement = placements.by_client[0];
  out.push(
    `${placements.count} ${plural(placements.count, "placement", "placementy", "placementów")} — ${change(placements.count, placements.previous)}.` +
      (topPlacement && placements.count > 1
        ? ` Najwięcej u klienta ${topPlacement.client} (${topPlacement.count}).`
        : ""),
  );

  const net = flows.starts - flows.ends;
  out.push(
    `Na projektach pracuje ${contractors.active} ${plural(contractors.active, "kontraktor", "kontraktorów", "kontraktorów")} ` +
      `(na koniec poprzedniego okresu ${contractors.previous}). W okresie zaczęło ${flows.starts}, odeszło ${flows.ends} — ` +
      `netto ${net > 0 ? "+" : ""}${net}.` +
      (contractors.by_client[0] && !contractors.by_client[0].rest
        ? ` Największy zespół: ${contractors.by_client[0].client} (${contractors.by_client[0].count}).`
        : ""),
  );

  if (exits.count > 0) {
    const top = exits.by_reason.find((r) => r.reason !== "unknown");
    const byConsultant = exits.items.filter((i) => CONSULTANT_REASONS.has(i.reason)).length;
    const byClient = exits.items.filter((i) => CLIENT_REASONS.has(i.reason)).length;
    const quality = exits.items.filter((i) => i.reason === "performance_issue").length;
    const unknown = exits.items.filter((i) => i.reason === "unknown").length;
    let text = `${exits.count} ${plural(exits.count, "zejście", "zejścia", "zejść")}`;
    if (top) text += `; najczęstszy powód: ${top.label} (${top.count})`;
    text += ".";
    if (byClient > 0 || byConsultant > 0) {
      text += ` Decyzja klienta (koniec projektu, cięcie budżetu, przejęcie): ${byClient}; decyzja konsultanta (rezygnacja, lepsza oferta, powody osobiste): ${byConsultant}.`;
    }
    if (byClient > byConsultant && byClient >= exits.count / 2) {
      text += " Większość zejść wynika z decyzji klientów — ryzyko leży w portfelu projektów, nie w ludziach.";
    } else if (byConsultant > byClient && byConsultant >= exits.count / 2) {
      text += " Większość odejść to decyzje konsultantów — do sprawdzenia stawki i opieka nad kontraktorem.";
    }
    if (quality > 0) {
      text += ` ${quality} ${plural(quality, "zejście", "zejścia", "zejść")} z powodu problemów jakościowych — sygnał dla selekcji i weryfikacji kandydatów.`;
    }
    if (unknown > 0) {
      text += ` Przy ${unknown} ${plural(unknown, "zejściu", "zejściach", "zejściach")} nie wpisano powodu.`;
    }
    out.push(text);
  } else {
    out.push("W okresie nikt nie zakończył kontraktu.");
  }

  if (flows.ends > 0 || placements.count > 0) {
    if (placements.count < flows.ends) {
      out.push(
        `Placementy (${placements.count}) nie pokrywają zejść (${flows.ends}) — baza kontraktorów maleje. ` +
          "Lejek musiałby dać więcej zatrudnień, żeby utrzymać przychód.",
      );
    } else {
      out.push(`Placementy (${placements.count}) pokrywają zejścia (${flows.ends}).`);
    }
  }
  if (funnelSentence) out.push(`Lejek: ${funnelSentence}`);
  return out;
}
