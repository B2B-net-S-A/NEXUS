/**
 * Okno „Zakończ współpracę" — czysta logika (ticket 09.2026, kontrakt #674).
 *
 * Kontrakt to PROJEKT (osoba × klient), a umowa B2B to umowa z osobą.
 * Okno rozróżnia samo zakończenie projektu (umowa trwa dalej) od rozwiązania
 * umowy (wypowiedzenie albo porozumienie stron). O statusie kontraktu decyduje
 * data zakończenia projektu — ostatni dzień umowy jej nie wydłuża.
 */
import type {
  AgreementTerminationMode,
  AgreementTerminationParty,
  AgreementTerminationPayload,
  ContractTerminationReason,
} from "@/lib/api";

export const AGREEMENT_TERMINATION_MODES: {
  value: AgreementTerminationMode;
  label: string;
}[] = [
  { value: "notice", label: "Wypowiedzenie" },
  { value: "mutual_agreement", label: "Porozumienie stron" },
];

export const AGREEMENT_TERMINATION_PARTIES: {
  value: AgreementTerminationParty;
  label: string;
}[] = [
  { value: "consultant", label: "Konsultant" },
  { value: "company", label: "b2bnetwork" },
];

export function agreementModeLabel(mode: string | null | undefined): string | null {
  if (!mode) return null;
  return AGREEMENT_TERMINATION_MODES.find((m) => m.value === mode)?.label ?? mode;
}

export function agreementPartyLabel(party: string | null | undefined): string | null {
  if (!party) return null;
  return AGREEMENT_TERMINATION_PARTIES.find((p) => p.value === party)?.label ?? party;
}

/** Etykieta daty zależy od trybu: złożenie wypowiedzenia vs zawarcie porozumienia. */
export function signedOnLabel(mode: AgreementTerminationMode | ""): string {
  return mode === "mutual_agreement"
    ? "Data zawarcia porozumienia"
    : "Data złożenia wypowiedzenia";
}

/** Typ dokumentu kontraktu dla załącznika z okna. */
export function attachmentDocType(
  mode: AgreementTerminationMode,
): "termination_notice" | "termination_agreement" {
  return mode === "notice" ? "termination_notice" : "termination_agreement";
}

/**
 * Podpowiedź „Ostatniego dnia umowy" przy wypowiedzeniu: data złożenia +
 * okres wypowiedzenia z umowy (miesiące). Dzień miesiąca przycinany do końca
 * krótszego miesiąca (31.01 + 1 mies. = 28/29.02). Brak okresu albo daty =
 * brak podpowiedzi — pole zostaje puste do uzupełnienia.
 */
export function suggestedLastDay(
  signedOn: string,
  noticePeriodMonths: number | null | undefined,
): string | null {
  if (!signedOn || !noticePeriodMonths || noticePeriodMonths < 1) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(signedOn);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]) - 1 + noticePeriodMonths;
  const day = Number(match[3]);
  const targetYear = year + Math.floor(month / 12);
  const targetMonth = month % 12;
  const lastOfMonth = new Date(Date.UTC(targetYear, targetMonth + 1, 0)).getUTCDate();
  const d = Math.min(day, lastOfMonth);
  return `${targetYear}-${String(targetMonth + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

export interface TerminationFormState {
  reason: ContractTerminationReason | "";
  projectEndDate: string;
  agreementTerminated: boolean;
  mode: AgreementTerminationMode | "";
  party: AgreementTerminationParty | "";
  signedOn: string;
  lastDay: string;
  lessons: string;
}

export function emptyTerminationForm(
  defaults: Partial<TerminationFormState> = {},
): TerminationFormState {
  return {
    reason: "",
    projectEndDate: "",
    agreementTerminated: false,
    mode: "",
    party: "",
    signedOn: "",
    lastDay: "",
    lessons: "",
    ...defaults,
  };
}

/** Czego brakuje, żeby „Zakończ" zapisało — puste = gotowe. */
export function missingTerminationFields(form: TerminationFormState): string[] {
  const missing: string[] = [];
  if (!form.reason) missing.push("Powód zakończenia");
  if (!form.projectEndDate) missing.push("Data zakończenia projektu");
  if (form.agreementTerminated) {
    if (!form.mode) missing.push("Tryb");
    if (!form.party) missing.push("Strona");
    if (!form.signedOn) missing.push(signedOnLabel(form.mode));
    if (!form.lastDay) missing.push("Ostatni dzień umowy");
  }
  return missing;
}

/** Błąd blokujący zapis (backend odmawia tego samego 422). */
export function terminationFormError(form: TerminationFormState): string | null {
  if (
    form.agreementTerminated &&
    form.signedOn &&
    form.lastDay &&
    form.lastDay < form.signedOn
  ) {
    return `Ostatni dzień umowy nie może być wcześniejszy niż ${
      form.mode === "mutual_agreement"
        ? "data zawarcia porozumienia"
        : "data złożenia wypowiedzenia"
    }.`;
  }
  return null;
}

/**
 * Ostrzeżenia, które NIE blokują zapisu (ticket, pkt 3). Daty ISO porównują
 * się leksykograficznie.
 */
export function terminationWarnings(
  form: TerminationFormState,
  orderEndDate?: string | null,
): string[] {
  const warnings: string[] = [];
  const end = form.projectEndDate;
  if (!end) return warnings;
  if (form.agreementTerminated && form.lastDay && end > form.lastDay) {
    warnings.push("Konsultant pracowałby na projekcie bez obowiązującej umowy.");
  }
  if (orderEndDate && end > orderEndDate) {
    warnings.push("Data zakończenia projektu wykracza poza okres zamówienia.");
  }
  return warnings;
}

export function agreementTerminationPayload(
  form: TerminationFormState,
): AgreementTerminationPayload | null {
  // Odznaczone pole: dodatkowe dane nie są wysyłane (ticket, pkt 2.4).
  if (!form.agreementTerminated || !form.mode || !form.party) return null;
  return {
    mode: form.mode,
    party: form.party,
    signed_on: form.signedOn,
    last_day: form.lastDay,
  };
}

interface StatusEventDetails {
  source?: string;
  contract_id?: number;
  project_end_date?: string | null;
  agreement_terminated?: boolean;
  mode?: string;
  party?: string;
  signed_on?: string;
  agreement_last_day?: string;
  previous_contract_number?: string;
}

function plDate(iso: string | null | undefined): string {
  const m = iso ? /^(\d{4})-(\d{2})-(\d{2})/.exec(iso) : null;
  return m ? `${m[3]}.${m[2]}.${m[1]}` : "—";
}

/**
 * Linia historii umowy w Generatorze dla zmian wykonanych przez zakończenie
 * kontraktu (0364). `null` = ręczna zmiana w Generatorze — bez dodatkowej linii.
 */
export function statusEventDetailsText(
  details: StatusEventDetails | null | undefined,
): string | null {
  if (!details?.source) return null;
  const contract = details.contract_id ? `kontrakt #${details.contract_id}` : "kontrakt";
  switch (details.source) {
    case "contract_termination_synced": {
      const parts = [`Zakończenie współpracy (${contract})`];
      if (details.project_end_date) {
        parts.push(`koniec zamówienia ${plDate(details.project_end_date)}`);
      }
      if (details.agreement_terminated && details.mode) {
        parts.push(agreementModeLabel(details.mode) ?? details.mode);
        const party = agreementPartyLabel(details.party);
        if (party) parts.push(`strona: ${party}`);
        if (details.signed_on) {
          parts.push(
            `${signedOnLabel(details.mode as AgreementTerminationMode).toLowerCase()} ${plDate(details.signed_on)}`,
          );
        }
        if (details.agreement_last_day) {
          parts.push(`ostatni dzień umowy ${plDate(details.agreement_last_day)}`);
        }
      } else {
        parts.push("umowa obowiązuje dalej");
      }
      return parts.join(" · ");
    }
    case "contract_termination_undone":
      return `Cofnięto zakończenie współpracy (${contract}) — przywrócono stan sprzed zakończenia`;
    case "contract_returned_after_break":
      return `Powrót po przerwie (${contract}) — projekt wznowiony`;
    case "created_after_break":
      return details.previous_contract_number
        ? `Nowa umowa po przerwie — poprzednia: ${details.previous_contract_number}`
        : "Nowa umowa po przerwie";
    default:
      return null;
  }
}
