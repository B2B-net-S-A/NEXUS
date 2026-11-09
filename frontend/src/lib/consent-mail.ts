/**
 * Prośba do kandydata o zgodę dla klienta z wymogiem zrzutu (dziś wyłącznie
 * PKO BP).
 *
 * Zapytania PKO niosą wzór z pustym „[Nazwa Dostawcy]”, więc kandydat dostaje
 * tekst uzupełniony nazwą firmy, swoim imieniem i nazwiskiem oraz numerem ZOB.
 */

export const SUPPLIER_NAME = "B2B.net S.A.";
const SUPPLIER_PLACEHOLDER = /\[\s*Nazwa\s+Dostawcy\s*\]/gi;
// Numer na rekrutacjach PKO bywa „ZOB-3109” i „ZOB 2996”.
const ZOB_NUMBER = /ZOB[\s-]*(\d+)/i;

export interface ConsentMail {
  subject: string;
  body: string;
}

/** API rekrutacji oddaje nazwę z rejestru („Powszechna Kasa Oszczędności…”), a nie „PKO BP”. */
export function isPkoClient(clientName: string | null | undefined): boolean {
  return /\bpko\b|powszechna\s+kasa\s+oszcz/i.test(clientName ?? "");
}

/** Nazwa klienta w zdaniu; pełna nazwa PKO z rejestru nie mieści się w pasku. */
export function consentClientLabel(clientName: string | null | undefined): string {
  return isPkoClient(clientName) ? "PKO BP" : clientName?.trim() || "Klient";
}

/** Numer zapytania z „Numeru u klienta”, a gdy go nie ma, z nazwy rekrutacji. */
export function zobReference(
  clientReference: string | null | undefined,
  title: string | null | undefined,
): string | null {
  const match = ZOB_NUMBER.exec(clientReference ?? "") ?? ZOB_NUMBER.exec(title ?? "");
  return match ? `ZOB-${match[1]}` : null;
}

export function buildConsentRequest(fullName: string, reference: string): ConsentMail {
  return {
    subject: `${reference} - zgoda na przetwarzanie danych osobowych`,
    body:
      `Dzień dobry,\n\n` +
      `PKO Bank Polski przyjmuje CV wyłącznie ze zgodą kandydata. Proszę o odpowiedź na tę wiadomość ` +
      `z poniższą treścią:\n\n---\n\n` +
      `Dzień dobry,\n\n` +
      `Ja, ${fullName}, wyrażam zgodę na przetwarzanie przez PKO Bank Polski moich danych osobowych ` +
      `zawartych w dokumencie CV, przekazanym przez ${SUPPLIER_NAME} („Oferent”) w ramach zapytania ` +
      `ofertowego nr ${reference}. Zgoda jest udzielona w celu umożliwienia wstępnej oceny kompetencji ` +
      `i doświadczenia do realizacji usług, które mają być realizowane z moim udziałem oraz przewidywanego ` +
      `sposobu ich realizacji. Przetwarzanie danych w oparciu o zgodę będzie odbywało się w okresie ` +
      `prowadzenia przez PKO Bank Polski postępowania ofertowego, o którym mowa powyżej oraz w okresie ` +
      `ewentualnego świadczenia przez Oferenta Usług na rzecz PKO Bank Polski z moim udziałem.`,
  };
}

export interface ConsentMailStatus {
  kind: "sent" | "replied";
  at: string;
}

interface ConsentThread {
  subject: string | null;
  latest: { direction: string; from_address?: string | null; sent_at: string | null; received_at: string };
}

/**
 * Stan prośby z wątków kandydata: wątek ma w temacie numer ZOB i słowo „zgoda”.
 * Odpowiedź liczy się po nadawcy: skrzynka firmy dostaje też kopię własnej prośby
 * jako wiadomość przychodzącą, sekundę po wysyłce.
 */
export function consentMailStatus(
  threads: ConsentThread[],
  reference: string,
  candidateEmail: string | null | undefined,
): ConsentMailStatus | null {
  const number = reference.replace(/\D/g, "");
  const thread = threads.find((t) => {
    const subject = t.subject ?? "";
    return /zgod/i.test(subject) && ZOB_NUMBER.exec(subject)?.[1] === number;
  });
  if (!thread || thread.latest.direction === "draft") return null;
  const fromCandidate =
    thread.latest.direction === "received" &&
    !!candidateEmail &&
    thread.latest.from_address?.toLowerCase() === candidateEmail.toLowerCase();
  return fromCandidate
    ? { kind: "replied", at: thread.latest.received_at }
    : { kind: "sent", at: thread.latest.sent_at ?? thread.latest.received_at };
}

/** Opis klienta na kawałki; `filled` = tu stał pusty wzór „[Nazwa Dostawcy]”. */
export function fillSupplierName(text: string): { value: string; filled: boolean }[] {
  const parts: { value: string; filled: boolean }[] = [];
  let last = 0;
  for (const match of text.matchAll(SUPPLIER_PLACEHOLDER)) {
    parts.push({ value: text.slice(last, match.index), filled: false });
    parts.push({ value: SUPPLIER_NAME, filled: true });
    last = match.index + match[0].length;
  }
  parts.push({ value: text.slice(last), filled: false });
  return parts;
}
