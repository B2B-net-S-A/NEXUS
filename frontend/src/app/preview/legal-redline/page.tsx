"use client";

/**
 * Harness „Popraw dokument” (asystent prawny, część D): tekst umowy ze
 * zmianami, lista „Przyjmij / Odrzuć / Zmień”, cytat bez pokrycia (zablokowana
 * zmiana), notatka „bez zmian” i pominięta propozycja.
 *
 * ZERO zapytań: sam widok `RedlineReview` z lokalnym stanem; przyciski pliku
 * pokazują tylko listę zmian, która poszłaby do `/api/legal/redline/render`.
 * Dane są fikcyjne.
 */

import { useState } from "react";
import { FileDiff, FileText, Scale } from "lucide-react";

import { RedlineReview } from "@/components/legal-assistant/redline/RedlineReview";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  acceptAll,
  acceptedChanges,
  summarize,
  type ChangeEdit,
  type Decision,
  type RedlineChange,
  type RedlineParagraph,
} from "@/lib/legal-redline";

const TEXTS = [
  "§ 4 Ogólne zasady współpracy",
  "Świadczenie Usług poza terytorium RP wymaga uprzedniej pisemnej zgody Zamawiającego lub Klienta.",
  "§ 9 Świadczenie Usług i odpowiedzialność",
  "Partner informuje Zamawiającego o przeszkodach w świadczeniu Usług bez zbędnej zwłoki.",
  "§ 13 Postanowienia końcowe",
  "Wszelkie zmiany Umowy wymagają formy pisemnej lub dokumentowej pod rygorem nieważności.",
  "Stawka",
  "Zgodnie z Załącznikiem nr 1",
];

const PARAGRAPHS: RedlineParagraph[] = TEXTS.map((text, index) => ({
  index,
  text,
  style: index % 2 === 0 && index < 6 ? "Nagwek1" : null,
  in_table: index >= 6,
  heading: index % 2 === 0 && index < 6,
}));

const at = (paragraph: number, find: string) => {
  const start = TEXTS[paragraph].indexOf(find);
  return { paragraph, find, start, end: start + find.length };
};

const CHANGES: RedlineChange[] = [
  {
    id: "a1",
    kind: "replace",
    ...at(1, "."),
    new_text:
      ". Świadczenie Usług z dostępem do danych Klienta spoza Europejskiego Obszaru Gospodarczego jest niedopuszczalne.",
    before: false,
    reason: "Wymóg bezpieczeństwa z umowy ramowej Banku Przykładowego.",
    sources: [
      {
        ref: "client-msa",
        label: "Umowa ramowa — pkt 9.4",
        quote: "nigdy spoza EOG",
        kind: "client",
        state: "ok",
      },
    ],
    blocked: false,
  },
  {
    id: "a2",
    kind: "insert_paragraph",
    paragraph: 1,
    find: "",
    start: null,
    end: null,
    new_text:
      "Na żądanie Zamawiającego Partner bierze udział w szkoleniach z bezpieczeństwa ICT organizowanych przez Klienta, w ramach wynagrodzenia określonego w § 6.",
    before: false,
    reason: "Aneks DORA klienta, pkt 2.7.",
    sources: [],
    blocked: false,
  },
  {
    id: "a3",
    kind: "replace",
    ...at(3, "bez zbędnej zwłoki"),
    new_text: "niezwłocznie, nie później niż w ciągu 24 godzin",
    before: false,
    reason: "Termin zgłaszania zdarzeń jak w aneksie DORA.",
    sources: [
      {
        ref: "kc-354",
        label: "art. 354 § 1 KC",
        quote: "zgodnie z jego treścią w sposób odpowiadający jego celowi",
        kind: "law",
        state: "mismatch",
      },
    ],
    blocked: true,
  },
  {
    id: "a4",
    kind: "replace",
    ...at(5, " pod rygorem nieważności."),
    new_text:
      " pod rygorem nieważności, z wyjątkiem zmian § 5, które wymagają formy pisemnej albo elektronicznej z kwalifikowanym podpisem elektronicznym.",
    before: false,
    reason: "Przeniesienie praw autorskich wymaga formy pisemnej.",
    sources: [
      {
        ref: "pr-aut-53",
        label: "art. 53 pr. aut.",
        quote: "Umowa o przeniesienie autorskich praw majątkowych wymaga zachowania formy pisemnej pod rygorem nieważności.",
        kind: "law",
        state: "ok",
      },
    ],
    blocked: false,
  },
  {
    id: "a5",
    kind: "replace",
    ...at(7, "nr 1"),
    new_text: "nr 2",
    before: false,
    reason: "Nowy załącznik ze stawką.",
    sources: [],
    blocked: false,
  },
];

export default function LegalRedlinePreview() {
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [edits, setEdits] = useState<Record<string, ChangeEdit>>({});
  const [sent, setSent] = useState<RedlineChange[] | null>(null);
  const summary = summarize(CHANGES, decisions, edits);
  const accepted = acceptedChanges(CHANGES, decisions, edits);

  return (
    <main className="mx-auto max-w-[1240px] space-y-3 bg-background p-4 text-foreground">
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-[13px]">
        <FileText className="size-4 text-muted-foreground" aria-hidden="true" />
        <span className="font-medium">Umowa B2B 12/2026 — Anna Przykładowa.docx</span>
        <span className="text-muted-foreground">·</span>
        <span className="text-muted-foreground">Polecenie:</span>
        <span>„Dostosuj do aneksu DORA i wymagań bezpieczeństwa Banku Przykładowego”</span>
        <Badge variant="info" size="sm" className="ml-auto">
          {summary.total} zmian · przyjęte {summary.accepted}
        </Badge>
      </div>

      <RedlineReview
        paragraphs={PARAGRAPHS}
        changes={CHANGES}
        decisions={decisions}
        edits={edits}
        notes={["Bez zmian: § 12 (wypowiedzenie 1 mies.) spełnia wymóg klienta o miesięcznym uprzedzeniu."]}
        dropped={[{ paragraph: 9, reason: "Zmiana wskazuje akapit, którego w dokumencie nie ma." }]}
        onDecide={(id, decision) => setDecisions((prev) => ({ ...prev, [id]: decision }))}
        onEdit={(id, edit) => setEdits((prev) => ({ ...prev, [id]: edit }))}
      />

      <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
        <p className="mr-auto flex items-center gap-1.5 text-[12px] text-muted-foreground">
          <Scale className="size-3.5" aria-hidden="true" />
          Asystent nie jest poradą prawną. Kara umowna, spór z klientem, rozwiązanie ze skutkiem natychmiastowym — do
          prawnika.
        </p>
        {summary.pending > 0 && (
          <Button size="sm" variant="ghost" onClick={() => setDecisions((prev) => acceptAll(CHANGES, prev, edits))}>
            Przyjmij wszystkie
          </Button>
        )}
        <Button size="sm" disabled={accepted.length === 0} onClick={() => setSent(accepted)}>
          <FileDiff className="mr-1.5 size-3.5" aria-hidden="true" /> Pobierz DOCX ze śledzeniem zmian
        </Button>
      </div>
      {sent && (
        <p role="status" className="text-[12px] text-muted-foreground">
          Harness: do pliku poszłyby zmiany {sent.map((c) => c.id).join(", ")}.
        </p>
      )}
    </main>
  );
}
