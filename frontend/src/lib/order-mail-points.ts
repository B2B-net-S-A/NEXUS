/**
 * „Do sprawdzenia” w kolejce zamówień z maila (przebudowa 20.11.2026, wariant A).
 *
 * Powody wstrzymania (`gate_reasons`) to proza z bramki. Do tej daty ekran
 * wypisywał je w jednej żółtej ramce; teraz każdy powód jest punktem z ikoną,
 * krótkim tytułem i podpowiedzią, co zrobić. API nie oddaje kodów powodów,
 * więc rodzaj punktu rozpoznajemy po treści — a czego nie rozpoznamy, zostaje
 * punktem „inne” z PEŁNYM zdaniem z bramki. Żaden powód nie może zniknąć:
 * nierozpoznany rodzaj to tylko brak podpowiedzi, nigdy brak treści.
 */
import {
  needsPersonDecision,
  type OrderMailDocument,
  type OrderMailProposalRow,
} from "@/lib/api/orderMail";
import { formatDateTimePl } from "@/lib/date-pl";
import { plural, withoutExceptionRepr } from "@/lib/order-mail-sync";

export type CheckPointKind =
  | "client"
  | "new_person"
  | "namesake"
  | "return"
  | "decide_person"
  | "no_people"
  | "uncertain"
  | "other";

export interface CheckPoint {
  kind: CheckPointKind;
  title: string;
  details: string[];
  /** „Co zrobić” — pokazywane tylko temu, kto może podjąć decyzję. */
  hint: string | null;
  links?: { href: string; label: string }[];
  /** Szczegóły schowane za „Uwagi odczytu (n)” — długie listy z odczytu PDF-a. */
  collapsible?: boolean;
}

const HINT = {
  client:
    "Uzupełnij NIP na karcie klienta — przy najbliższym sprawdzeniu system sam spróbuje rozpoznać klienta ponownie. Gdy to nie zamówienie od klienta, odrzuć wpis.",
  newPerson:
    "Zamówienie zapisze się samo w ciągu godziny od podpisania umowy B2B. Gdy umowy B2B nie będzie (umowa o pracę, zlecenie), kliknij „Zastosuj” — powstanie szkic do uzupełnienia.",
  namesake:
    "Porównaj obie osoby. Jeśli to ta sama osoba, kliknij „Zastosuj” — zapis dopnie istniejącą kartę zamiast zakładać drugą.",
  returnAfterBreak: "„Zastosuj” założy nowe zamówienie na nowy okres; poprzednie zostaje bez zmian.",
  decidePerson:
    "W oknie zamówienia klienta zdecydujesz, czy zostawić ją jako zapis historyczny, wznowić współpracę, zastąpić inną osobą czy usunąć z zamówienia. Okno otworzy się z tym PDF-em.",
  noPeople: "Wprowadź zamówienie ręcznie w oknie zamówienia klienta, a potem odrzuć ten wpis.",
  uncertain: "Porównaj plan z tabelą osób w PDF-ie; jeśli się zgadza, kliknij „Zastosuj”.",
} as const;

/** Krótka etykieta pierwszego punktu w wierszu kolejki. */
const SHORT_LABEL: Record<Exclude<CheckPointKind, "other">, string> = {
  client: "Nie rozpoznano klienta",
  new_person: "Nowa osoba bez umowy",
  namesake: "Imiennik w bazie",
  return: "Powrót po przerwie",
  decide_person: "Osoba do rozstrzygnięcia",
  no_people: "Nie odczytano osób",
  uncertain: "Niepewny odczyt PDF",
};

export function pointShortLabel(point: CheckPoint): string {
  return point.kind === "other" ? point.title : SHORT_LABEL[point.kind];
}

const NO_PEOPLE =
  /^(Brak osób do dopasowania|Dokument bez rozpoznanych osób|Brak niezależnego potwierdzenia osób i stawek)/;
const UNCERTAIN_PREFIX = /^Odczyt niepewny:\s*/;
const PERSON_REASON = /^„([^”]+)”:\s*([\s\S]+)$/;
const NAMESAKE =
  /inna osoba o tym imieniu i nazwisku|jest już w bazie|w bazie jest kilka osób o tym imieniu|ma kontrakt #\d+ u klienta/;
const NAMESAKE_TAIL =
  /\s*(?:—\s*potwierdź[\s\S]*|\.\s*Potwierdź, że to ta sama osoba[\s\S]*|\.\s*Sprawdź, czy dokument nie dotyczy[\s\S]*)$/;
const DECIDE_PERSON = /nie ma już aktywnej współpracy|^Nie znaleziono .+ w systemie/;
const DECIDE_TAIL = /\s*(?:Zdecyduj:[\s\S]*|Wskaż tę osobę ręcznie[\s\S]*)$/;

const upperFirst = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const lowerFirst = (s: string) => s.charAt(0).toLowerCase() + s.slice(1);

/**
 * Jeden powód osoby bywa sklejony z kilku zdań planera („Powrót po 1 dniu…;
 * W bazie jest też inna osoba…”). Dzielimy tylko przed wielką literą albo
 * cudzysłowem — średnik w środku zdania („kontrakt #1 u klienta „A”;
 * kontrakt #2 …”) zostaje w jednym punkcie.
 */
function splitParts(body: string): string[] {
  return body
    .split(/;\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ„])/)
    .map((p) => p.trim())
    .filter(Boolean);
}

function quotedNames(texts: string[]): string[] {
  const names = new Set<string>();
  for (const t of texts) for (const m of t.matchAll(/„([^”]+)”/g)) names.add(m[1]);
  return [...names];
}

function personLinks(who: string, rows: OrderMailProposalRow[]): { href: string; label: string }[] {
  const row = rows.find((r) => r.row_name === who);
  if (!row) return [];
  const links: { href: string; label: string }[] = [];
  if (row.candidate_id) links.push({ href: `/candidates/${row.candidate_id}`, label: "Osoba na kontrakcie" });
  for (const id of row.existing_person_ids ?? []) {
    if (id !== row.candidate_id) links.push({ href: `/candidates/${id}`, label: `Osoba w bazie #${id}` });
  }
  return links;
}

function decidePoint(who: string, text: string): CheckPoint {
  const fact = text.replace(DECIDE_TAIL, "").trim();
  return {
    kind: "decide_person",
    title: `${who} — decyzja o osobie w oknie zamówienia`,
    details: fact ? [upperFirst(fact)] : [],
    hint: HINT.decidePerson,
  };
}

function personPoint(raw: string, who: string, part: string, rows: OrderMailProposalRow[]): CheckPoint {
  if (/czeka na podpisaną umowę/.test(part)) {
    const fact = part.replace(/\s*—\s*zamówienie czeka na podpisaną umowę B2B\.?$/, "").trim();
    return {
      kind: "new_person",
      title: `${who} — nowa osoba bez umowy`,
      details: fact ? [upperFirst(fact)] : [],
      hint: HINT.newPerson,
    };
  }
  if (NAMESAKE.test(part)) {
    const fact = part.replace(NAMESAKE_TAIL, "").trim();
    const links = personLinks(who, rows);
    return {
      kind: "namesake",
      title: `${who} — w bazie jest osoba o tym imieniu i nazwisku`,
      details: [upperFirst(fact || part)],
      hint: /kilka osób/.test(part) ? null : HINT.namesake,
      ...(links.length ? { links } : {}),
    };
  }
  if (/^Powrót po/.test(part)) {
    return { kind: "return", title: `${who} — ${lowerFirst(part)}`, details: [], hint: HINT.returnAfterBreak };
  }
  if (DECIDE_PERSON.test(part)) return decidePoint(who, part);
  // Rodzaj nierozpoznany: pełne zdanie z bramki, bez podpowiedzi.
  return { kind: "other", title: raw, details: [], hint: null };
}

/**
 * Punkty „Do sprawdzenia” dla wpisu. Kolejność: klient, powody osób w kolejności
 * bramki, osoba do rozstrzygnięcia z planu, brak osób, niepewny odczyt.
 */
export function checkPoints(doc: OrderMailDocument): CheckPoint[] {
  const points: CheckPoint[] = [];
  const uncertain: string[] = [];
  const noPeople: string[] = [];
  const rows = doc.proposal?.rows ?? [];
  if (doc.outcome === "unrecognized_client") {
    points.push({
      kind: "client",
      title: "Nie rozpoznano klienta",
      details: doc.identification_reason ? [doc.identification_reason] : [],
      hint: HINT.client,
    });
  }
  for (const reason of doc.gate_reasons ?? []) {
    const text = withoutExceptionRepr(reason).trim();
    if (!text) continue;
    if (UNCERTAIN_PREFIX.test(text)) {
      uncertain.push(upperFirst(text.replace(UNCERTAIN_PREFIX, "")));
      continue;
    }
    if (NO_PEOPLE.test(text)) {
      noPeople.push(text);
      continue;
    }
    const m = PERSON_REASON.exec(text);
    if (!m) {
      points.push({ kind: "other", title: text, details: [], hint: null });
      continue;
    }
    const parts = splitParts(m[2]);
    for (const part of parts) {
      // Jedno zdanie = cały powód z bramki w „innych”; kilka zdań = każde osobno.
      const raw = parts.length === 1 ? text : `„${m[1]}”: ${part}`;
      points.push(personPoint(raw, m[1], part, rows));
    }
  }
  // Osoba do rozstrzygnięcia wynika z PLANU — bramka nie zawsze dopisuje o niej
  // zdanie, a bez punktu ekran nie mówiłby, dlaczego „Zastosuj” jest wyłączone.
  if (needsPersonDecision(doc) && !points.some((p) => p.kind === "decide_person")) {
    for (const row of rows.filter((r) => r.action === "decide_person")) {
      points.push(decidePoint(row.row_name, row.reasons.join(" ")));
    }
  }
  if (noPeople.length) {
    points.push({
      kind: "no_people",
      title: "Nie odczytano osób ani stawek",
      details: [...noPeople, ...uncertain.splice(0)],
      hint: HINT.noPeople,
      collapsible: true,
    });
  }
  if (uncertain.length) {
    const names = quotedNames(uncertain).map((n) => `„${n}”`);
    points.push({
      kind: "uncertain",
      title: names.length
        ? `Niepewny odczyt PDF — ${names.join(names.length === 2 ? " czy " : ", ")}`
        : "Niepewny odczyt PDF",
      details: uncertain,
      hint: HINT.uncertain,
      collapsible: uncertain.length > 1,
    });
  }
  return points;
}

/** Czy wpis czeka na decyzję człowieka — tylko wtedy punkty mówią „co zrobić”. */
export function awaitsDecision(doc: Pick<OrderMailDocument, "outcome">): boolean {
  return doc.outcome === "needs_review" || doc.outcome === "unrecognized_client";
}

/** Czy zalogowany może coś z wpisem zrobić — inaczej podpowiedzi „kliknij…” kłamią. */
export function canActOn(doc: Pick<OrderMailDocument, "outcome" | "can_apply" | "can_dismiss">): boolean {
  return doc.outcome === "needs_review" ? doc.can_apply : doc.can_dismiss === true;
}

const IDENT_LABEL: Record<string, string> = {
  registry_id: "rozpoznany po numerze rejestrowym z PDF-a",
  marker: "rozpoznany po znaczniku klienta w PDF-ie",
  sender_domain: "rozpoznany po domenie nadawcy",
};

/** Jak rozpoznano klienta i czyje reguły czytały PDF — słowami, bez kodów. */
export function identLabel(
  doc: Pick<OrderMailDocument, "client_id" | "client_name" | "identification_method" | "client_policy">,
): string {
  if (!doc.client_id && !doc.client_name) return "nie rozpoznano";
  const how = doc.identification_method
    ? (IDENT_LABEL[doc.identification_method] ?? "rozpoznany automatycznie")
    : "rozpoznany automatycznie";
  return `${how} · ${doc.client_policy ? `reguły odczytu: ${doc.client_policy}` : "bez własnych reguł odczytu"}`;
}

/**
 * Nadawca maila: imię i nazwisko z adresu osoby („jan.kowalski@…” → „Jan
 * Kowalski”), a skrzynka działu („zamowienia@…”) zostaje adresem — z samego
 * „zamowienia” nikt nie odgadnie, kto przysłał dokument.
 */
export function senderLabel(email: string | null | undefined): string {
  if (!email) return "nieznanego nadawcy";
  const [local, domain] = email.split("@");
  if (!domain) return email;
  const parts = local.split(/[._-]+/).filter(Boolean);
  if (parts.length >= 2 && parts.every((p) => /^\p{L}+$/u.test(p))) {
    return parts.map((p) => upperFirst(p.toLowerCase())).join(" ");
  }
  return email;
}

interface RecheckMeta {
  attempts?: number;
  last_at?: string;
  category?: string;
}

/** Co robi automat z tym wpisem (`document_meta.recheck`) — jedno zdanie albo nic. */
export function recheckLine(
  doc: Pick<OrderMailDocument, "outcome" | "document_meta" | "can_apply" | "can_dismiss" | "proposal">,
): string | null {
  if (!awaitsDecision(doc)) return null;
  const r = (doc.document_meta?.recheck ?? null) as RecheckMeta | null;
  if (!r) return null;
  const when = r.last_at ? `, ostatnio ${formatDateTimePl(r.last_at)}` : "";
  if (r.category === "awaiting_contract") {
    return "Czeka na podpis umowy — system sprawdza ten wpis co godzinę i zapisze go sam, bez powiadomienia.";
  }
  if (r.category === "unrecognized") return `System co godzinę próbuje rozpoznać klienta${when}.`;
  const n = Number(r.attempts ?? 0);
  if (!n) return null;
  const decide = !canActOn(doc)
    ? "decyzja należy do admina albo Delivery Leada klienta"
    : doc.outcome === "needs_review" && applyBlockedReason(doc) == null
      ? "zdecyduj: „Zastosuj” albo „Odrzuć”"
      : "czeka na Twoją decyzję";
  return `Automat sprawdził ten wpis ${n} ${plural(n, "raz", "razy", "razy")}${when} i nadal go wstrzymuje — ${decide}.`;
}

/**
 * Powody wiersza planu, których nie ma już w punktach „Do sprawdzenia”. Bramka
 * składa powód osoby z tych samych zdań, więc bez tego ekran mówił każde zdanie
 * dwa razy: w tabeli planu i w ramce pod nią.
 */
export function rowReasonsOutsideGate(row: Pick<OrderMailProposalRow, "reasons">, gateReasons: readonly string[]): string[] {
  const gate = gateReasons.map((r) => withoutExceptionRepr(r));
  return row.reasons.filter((reason) => !gate.some((g) => g.includes(reason)));
}

const FAILED_MANUAL_NOTE =
  "Nie będzie ponawiany — wprowadź zamówienie ręcznie w oknie zamówienia klienta i odrzuć wpis.";
// Bez prawa odrzucenia (`can_dismiss` z serwera) zdanie nie każe klikać
// przycisku, którego ta osoba nie ma (np. Finanse bez portfela — runda 3
// audytu 25.09.2026).
const FAILED_MANUAL_NOTE_READ_ONLY =
  "Nie będzie ponawiany — zamówienie trzeba wprowadzić ręcznie w oknie zamówienia klienta; wpis odrzuci admin albo Delivery Lead klienta.";

/**
 * Zdanie o automatycznych ponowieniach wpisu „Nieudane”.
 *
 * „System ponawia sam” tylko wtedy, gdy serwer tak liczy (`failed_retry_pending`:
 * plik jest, wpis młodszy niż 7 dni, mniej niż 3 próby). Do rundy 2 audytu
 * 25.09.2026 zdanie obiecywało ponowienia także wpisom bez pliku i starszym
 * niż 7 dni, których system nigdy już nie weźmie.
 */
export function failedRetryNote(
  doc: Pick<OrderMailDocument, "document_meta" | "failed_retry_pending" | "can_dismiss">,
): string {
  const retry = (doc.document_meta?.failed_retry ?? null) as { attempts?: number } | null;
  const attempts = Number(retry?.attempts ?? 0);
  if (doc.failed_retry_pending === true) {
    return `Przetwarzanie nie powiodło się. System ponawia je sam z zapisanego PDF-a (próba ${attempts} z 3, przez 7 dni od nadejścia maila).`;
  }
  const manual = doc.can_dismiss === true ? FAILED_MANUAL_NOTE : FAILED_MANUAL_NOTE_READ_ONLY;
  if (attempts >= 3) {
    return `System próbował przetworzyć ten dokument ponownie 3 razy bez skutku. ${manual}`;
  }
  return manual;
}

/** Dlaczego „Zastosuj” jest wyłączone — zdanie obok przycisku i w jego `title`. */
export function applyBlockedReason(
  doc: Pick<OrderMailDocument, "can_apply" | "proposal">,
): string | null {
  if (!doc.can_apply) return "Zapis wymaga admina albo przypisanego Delivery Leada";
  if (needsPersonDecision(doc)) {
    return "Osobę z zakończoną współpracą albo nieznalezioną rozstrzygnij w oknie zamówienia";
  }
  if (!(doc.proposal?.rows?.length ?? 0)) return "Brak osób w planie — wprowadź zamówienie ręcznie w oknie zamówienia klienta";
  return null;
}
