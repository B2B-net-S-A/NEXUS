/**
 * „Do sprawdzenia” w kolejce zamówień z maila (20.11.2026): powody z bramki
 * jako punkty z podpowiedzią. Najważniejsza reguła: żaden powód nie znika —
 * nierozpoznany rodzaj zostaje punktem „inne” z pełnym zdaniem.
 * Dane fikcyjne (repo jest publiczne).
 */
import { describe, expect, it } from "vitest";

import type { OrderMailDocument, OrderMailProposalRow } from "@/lib/api/orderMail";
import {
  applyBlockedReason,
  canActOn,
  checkPoints,
  identLabel,
  pointShortLabel,
  recheckLine,
  rowReasonsOutsideGate,
  senderLabel,
} from "@/lib/order-mail-points";

function row(over: Partial<OrderMailProposalRow> = {}): OrderMailProposalRow {
  return {
    row_index: 0, row_name: "Zenon Przykładowy", action: "new", candidate_id: 10, contract_id: 20, target_order_id: null,
    title: "7/2031", start_date: "2031-04-01", end_date: "2031-06-30", rate_client: "900.00", rate_unit: "day",
    md_total: null, reasons: [], ...over,
  };
}

function doc(over: Partial<OrderMailDocument> = {}): OrderMailDocument {
  return {
    id: 1, received_at: "2031-03-03T08:00:00Z", sender_email: "zamowienia@bank.example", subject: "Zamówienie",
    attachment_name: "z.pdf", outcome: "needs_review", client_id: 1, client_name: "Bank Przykładowy",
    identification_method: "registry_id", identification_reason: null, client_policy: "Bank Przykładowy",
    gate_verdict: "review", gate_reasons: [], document_meta: null, extraction: null,
    proposal: { client_id: 1, order_number: "7/2031", is_group_client: false, blocking: [], rows: [row()] },
    applied_order_id: null, applied_at: null, reviewed_at: null, error: null, can_apply: true, has_file: true,
    ...over,
  };
}

const NEW_PERSON =
  "„Zenon Przykładowy”: nie ma jej wśród konsultantów tego klienta ani w bazie — zamówienie czeka na podpisaną umowę B2B";

describe("checkPoints", () => {
  it("nowa osoba bez umowy: tytuł z osobą, fakt bez ogona i podpowiedź o podpisie", () => {
    const [p] = checkPoints(doc({ gate_reasons: [NEW_PERSON] }));
    expect(p.kind).toBe("new_person");
    expect(p.title).toBe("Zenon Przykładowy — nowa osoba bez umowy");
    expect(p.details).toEqual(["Nie ma jej wśród konsultantów tego klienta ani w bazie"]);
    expect(p.hint).toContain("w ciągu godziny od podpisania umowy B2B");
    expect(pointShortLabel(p)).toBe("Nowa osoba bez umowy");
  });

  it("jeden powód z dwoma zdaniami planera daje dwa punkty: powrót i imiennik z linkami", () => {
    const reason =
      "„Wiesław Powracający”: Powrót po 1 dniu od zakończenia poprzedniego zamówienia; W bazie jest też inna osoba o tym imieniu i nazwisku (#9001) — potwierdź, że to powrót tej samej osoby, i zastosuj ręcznie";
    const points = checkPoints(
      doc({
        gate_reasons: [reason],
        proposal: {
          client_id: 1, order_number: "7/2031", is_group_client: false, blocking: [],
          rows: [row({ row_name: "Wiesław Powracający", action: "reactivate", candidate_id: 9000, existing_person_ids: [9001] })],
        },
      }),
    );
    expect(points.map((p) => p.kind)).toEqual(["return", "namesake"]);
    expect(points[0].title).toBe("Wiesław Powracający — powrót po 1 dniu od zakończenia poprzedniego zamówienia");
    expect(points[1].details).toEqual(["W bazie jest też inna osoba o tym imieniu i nazwisku (#9001)"]);
    expect(points[1].links).toEqual([
      { href: "/candidates/9000", label: "Osoba na kontrakcie" },
      { href: "/candidates/9001", label: "Osoba w bazie #9001" },
    ]);
  });

  it("średnik w środku zdania (kilka kontraktów osoby) nie rozbija punktu", () => {
    const reason =
      "„Anna Wzorowa”: „Anna Wzorowa” (#11) ma kontrakt #1 u klienta „Firma A”; kontrakt #2 u klienta „Firma B”. Sprawdź, czy dokument nie dotyczy tego samego klienta zapisanego pod drugim rekordem, zanim założysz nowego kontraktora";
    const points = checkPoints(doc({ gate_reasons: [reason] }));
    expect(points).toHaveLength(1);
    expect(points[0].kind).toBe("namesake");
    expect(points[0].details[0]).toContain("kontrakt #2 u klienta „Firma B”");
  });

  it("kilka imienników: bez podpowiedzi „Zastosuj” — automat nie zgaduje", () => {
    const [p] = checkPoints(
      doc({
        gate_reasons: [
          "„Jan Wzorcowy”: w bazie jest kilka osób o tym imieniu i nazwisku („Jan Wzorcowy” (#1), „Jan Wzorcowy” (#2)) — wskaż właściwą ręcznie, automat nie zgaduje",
        ],
      }),
    );
    expect(p.kind).toBe("namesake");
    expect(p.hint).toBeNull();
  });

  it("niepewny odczyt: jeden punkt z nazwami, uwagi zwinięte przy kilku", () => {
    const points = checkPoints(
      doc({
        gate_reasons: [
          NEW_PERSON,
          "Odczyt niepewny: „Jan Kowalski”: osoby z tabeli Consultant(s) nie potwierdził odczyt modelu — sprawdź imię i nazwisko",
          "Odczyt niepewny: „Jan Kowalski Nowak”: pozycja z odczytu modelu nie ma wiersza w tabeli Consultant(s) PDF — sprawdź",
        ],
      }),
    );
    expect(points.map((p) => p.kind)).toEqual(["new_person", "uncertain"]);
    const uncertain = points[1];
    expect(uncertain.title).toBe("Niepewny odczyt PDF — „Jan Kowalski” czy „Jan Kowalski Nowak”");
    expect(uncertain.details).toHaveLength(2);
    expect(uncertain.details[0]).toMatch(/^„Jan Kowalski”: osoby z tabeli/);
    expect(uncertain.collapsible).toBe(true);
    // Jedna uwaga stoi od razu, bez przycisku.
    expect(checkPoints(doc({ gate_reasons: ["Odczyt niepewny: brak stawki"] }))[0]).toMatchObject({
      title: "Niepewny odczyt PDF",
      details: ["Brak stawki"],
      collapsible: false,
    });
  });

  it("brak osób zbiera powody bramki i uwagi odczytu w jeden punkt — nic nie znika", () => {
    const gate = [
      "Brak osób do dopasowania",
      "Brak niezależnego potwierdzenia osób i stawek z pól dokumentu PDF",
      "Odczyt niepewny: Brak listy konsultantów w dokumencie",
      "Dokument bez rozpoznanych osób",
    ];
    const points = checkPoints(doc({ gate_reasons: gate, proposal: null }));
    expect(points).toHaveLength(1);
    expect(points[0]).toMatchObject({ kind: "no_people", title: "Nie odczytano osób ani stawek", collapsible: true });
    expect(points[0].details).toEqual([gate[0], gate[1], gate[3], "Brak listy konsultantów w dokumencie"]);
  });

  it("nierozpoznany rodzaj zostaje pełnym zdaniem z bramki, bez podpowiedzi", () => {
    const reasons = [
      "„Jan Kowalski”: Dopasowanie z literówką — potwierdź osobę",
      "Klient nie ma własnej polityki odczytu",
      "Nie udało się zapisać zamówienia: ValueError('W bazie jest już osoba — zastosuj ręcznie')",
    ];
    const points = checkPoints(doc({ gate_reasons: reasons }));
    expect(points.map((p) => [p.kind, p.title, p.hint])).toEqual([
      ["other", reasons[0], null],
      ["other", reasons[1], null],
      ["other", "Nie udało się zapisać zamówienia: W bazie jest już osoba — zastosuj ręcznie", null],
    ]);
    // W wierszu kolejki „inne” mówi swoim zdaniem, nie „Inna uwaga”.
    expect(pointShortLabel(points[1])).toBe("Klient nie ma własnej polityki odczytu");
  });

  it("osoba do rozstrzygnięcia: z powodu bramki albo — gdy go nie ma — z planu", () => {
    const inactive =
      "„Marian Odchodzący” nie ma już aktywnej współpracy u tego klienta (kontrakt zakończony 12.02.2031). Zdecyduj: zostaw tę osobę na zamówieniu jako zapis historyczny, wznów współpracę, zastąp ją inną osobą albo usuń z zamówienia";
    const decideRow = row({ row_name: "Marian Odchodzący", action: "decide_person", reasons: [inactive] });
    const proposal = { client_id: 1, order_number: "SAP 1", is_group_client: true, blocking: [], rows: [decideRow] };
    const fromGate = checkPoints(doc({ proposal, gate_reasons: [`„Marian Odchodzący”: ${inactive}`] }));
    expect(fromGate).toHaveLength(1);
    expect(fromGate[0]).toMatchObject({ kind: "decide_person", title: "Marian Odchodzący — decyzja o osobie w oknie zamówienia" });
    expect(fromGate[0].details).toEqual([
      "„Marian Odchodzący” nie ma już aktywnej współpracy u tego klienta (kontrakt zakończony 12.02.2031).",
    ]);
    expect(fromGate[0].hint).toContain("zostawić ją jako zapis historyczny");
    const fromPlan = checkPoints(doc({ proposal, gate_reasons: [] }));
    expect(fromPlan.map((p) => p.kind)).toEqual(["decide_person"]);
    const unknown = checkPoints(
      doc({
        gate_reasons: [
          "„Ewa Nieznana”: Nie znaleziono „Ewa Nieznana” w systemie — brak kontraktu z tym imieniem i nazwiskiem u tego klienta (system nie koryguje literówek ani nie zgaduje podobieństwa). Wskaż tę osobę ręcznie, zastąp ją kimś innym albo usuń z zamówienia",
        ],
      }),
    );
    expect(unknown[0].kind).toBe("decide_person");
    expect(unknown[0].details[0]).not.toContain("Wskaż tę osobę");
  });

  it("nierozpoznany klient ma własny punkt z powodem rozpoznania", () => {
    const [p] = checkPoints(
      doc({ outcome: "unrecognized_client", client_id: null, client_name: null, identification_reason: "Żaden numer nie pasuje." }),
    );
    expect(p).toMatchObject({ kind: "client", title: "Nie rozpoznano klienta", details: ["Żaden numer nie pasuje."] });
    expect(p.hint).toContain("NIP");
  });

  it("puste powody nie dają punktów", () => {
    expect(checkPoints(doc({ gate_reasons: ["", "   "] }))).toEqual([]);
  });
});

describe("recheckLine", () => {
  const meta = (recheck: object) => ({ recheck });

  it("czekanie na podpis i nierozpoznany klient mają własne zdanie", () => {
    expect(recheckLine(doc({ document_meta: meta({ category: "awaiting_contract", attempts: 0 }) }))).toContain(
      "zapisze go sam",
    );
    expect(
      recheckLine(doc({ outcome: "unrecognized_client", document_meta: meta({ category: "unrecognized", last_at: null }) })),
    ).toBe("System co godzinę próbuje rozpoznać klienta.");
  });

  it("liczba prób z odmianą i decyzją dopasowaną do praw i planu", () => {
    const line = recheckLine(doc({ document_meta: meta({ category: "other", attempts: 3 }) }));
    expect(line).toBe("Automat sprawdził ten wpis 3 razy i nadal go wstrzymuje — zdecyduj: „Zastosuj” albo „Odrzuć”.");
    expect(recheckLine(doc({ document_meta: meta({ attempts: 1 }) }))).toContain("1 raz ");
    // Wtrącenie z datą zamknięte przecinkiem.
    expect(recheckLine(doc({ document_meta: meta({ attempts: 2, last_at: "2031-03-03T08:00:00Z" }) }))).toMatch(
      /^Automat sprawdził ten wpis 2 razy, ostatnio \d{2}\.\d{2}\.2031 \d{2}:\d{2}, i nadal go wstrzymuje/,
    );
    expect(recheckLine(doc({ can_apply: false, document_meta: meta({ attempts: 5 }) }))).toContain(
      "decyzja należy do admina albo Delivery Leada klienta",
    );
    // „Zastosuj” wyłączone (brak osób w planie) — zdanie nie każe go klikać.
    expect(recheckLine(doc({ proposal: null, document_meta: meta({ attempts: 5 }) }))).toContain("czeka na Twoją decyzję");
  });

  it("milczy przy zapisanych, bez śladu automatu i przy zerze prób", () => {
    expect(recheckLine(doc({ outcome: "applied", document_meta: meta({ attempts: 3 }) }))).toBeNull();
    expect(recheckLine(doc({ document_meta: null }))).toBeNull();
    expect(recheckLine(doc({ document_meta: meta({ attempts: 0, category: "other" }) }))).toBeNull();
  });
});

describe("rowReasonsOutsideGate", () => {
  it("chowa zdania, które bramka już powiedziała, zostawia resztę", () => {
    const r = row({ reasons: ["Powrót po 1 dniu od zakończenia poprzedniego zamówienia", "Osoba bez kontraktu do zapisu"] });
    const gate = ["„Zenon Przykładowy”: Powrót po 1 dniu od zakończenia poprzedniego zamówienia"];
    expect(rowReasonsOutsideGate(r, gate)).toEqual(["Osoba bez kontraktu do zapisu"]);
    expect(rowReasonsOutsideGate(r, [])).toEqual(r.reasons);
  });
});

describe("applyBlockedReason i canActOn", () => {
  it("kolejność: prawa, osoba do rozstrzygnięcia, pusty plan", () => {
    expect(applyBlockedReason(doc({ can_apply: false }))).toContain("Delivery Leada");
    const decide = { client_id: 1, order_number: null, is_group_client: true, blocking: [], rows: [row({ action: "decide_person" })] };
    expect(applyBlockedReason(doc({ proposal: decide }))).toContain("w oknie zamówienia");
    expect(applyBlockedReason(doc({ proposal: null }))).toContain("Brak osób w planie");
    expect(applyBlockedReason(doc())).toBeNull();
  });

  it("do weryfikacji decyduje `can_apply`, nierozpoznane i nieudane — `can_dismiss`", () => {
    expect(canActOn(doc({ can_apply: false }))).toBe(false);
    expect(canActOn(doc({ outcome: "unrecognized_client", can_apply: false, can_dismiss: true }))).toBe(true);
    expect(canActOn(doc({ outcome: "failed", can_apply: false }))).toBe(false);
  });
});

describe("identLabel i senderLabel", () => {
  it("rozpoznanie słowami, nie kodem", () => {
    expect(identLabel(doc())).toBe("rozpoznany po numerze rejestrowym z PDF-a · reguły odczytu: Bank Przykładowy");
    expect(identLabel(doc({ identification_method: "sender_domain", client_policy: null }))).toBe(
      "rozpoznany po domenie nadawcy · bez własnych reguł odczytu",
    );
    expect(identLabel(doc({ client_id: null, client_name: null }))).toBe("nie rozpoznano");
  });

  it("adres osoby to imię i nazwisko, skrzynka działu zostaje adresem", () => {
    expect(senderLabel("jan.kowalski@firma.example")).toBe("Jan Kowalski");
    expect(senderLabel("ANNA_NOWAK@firma.example")).toBe("Anna Nowak");
    expect(senderLabel("zamowienia@bank.example")).toBe("zamowienia@bank.example");
    expect(senderLabel("dzial.zakupow2@bank.example")).toBe("dzial.zakupow2@bank.example");
    expect(senderLabel(null)).toBe("nieznanego nadawcy");
  });
});
