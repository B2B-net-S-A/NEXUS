/**
 * Jeden słownik powodów zamknięcia procesu kandydata (decyzja Artura
 * 19.11.2026, wariant A okna „Zamknij proces”). Lustro
 * `backend/app/services/close_reasons.py` — klucze, „kto wybiera”, `earlyOnly`
 * i nazwy wierszy szablonu muszą się zgadzać (`test_close_reasons.py`).
 *
 * Klucz powodu jest jednocześnie powodem dla systemu (`AutofillReason`), więc
 * okno pyta raz, a powód z szablonu wynika 1:1. Etykiety tu są krótsze niż
 * w historii, bo stoją w grupie („Klient → Nie podał powodu”).
 */
import type { AutofillReason } from "@/lib/autofill-feedback";

/** Kto kończy proces: my (rekruter albo Delivery Lead), klient, kandydat. */
export type CloseWho = "recruiter" | "client" | "candidate";

/** Klucz słownika: powód dla systemu albo powód tylko kandydata (rezygnacja). */
export type CloseReasonKey = AutofillReason | "counter_offer" | "lost_interest" | "personal_reasons";

export interface CloseReason {
  key: CloseReasonKey;
  label: string;
  who: readonly CloseWho[];
  /** `rejection_reasons.name` przy odrzuceniu (my, DL, klient). */
  rejected?: string;
  /** `rejection_reasons.name` przy rezygnacji (kandydat). */
  withdrawn?: string;
  /** Tylko w „Nowych”/„Screeningu” — dane w bazie, telefon. */
  earlyOnly?: boolean;
}

export interface CloseReasonGroup {
  title: string;
  reasons: CloseReason[];
}

const ALL: CloseWho[] = ["recruiter", "client", "candidate"];
const US_CLIENT: CloseWho[] = ["recruiter", "client"];
const US_CANDIDATE: CloseWho[] = ["recruiter", "candidate"];
const CLIENT: CloseWho[] = ["client"];
const CANDIDATE: CloseWho[] = ["candidate"];

export const CLOSE_REASON_GROUPS: CloseReasonGroup[] = [
  {
    title: "Klient",
    reasons: [
      { key: "client_chose_other", label: "Wybrał innego kandydata", who: CLIENT, rejected: "client_chose_other" },
      { key: "client_interview_weak", label: "Rozmowa wypadła słabo", who: CLIENT, rejected: "client_interview_weak" },
      { key: "client_project_closed", label: "Projekt zamknięty / przetarg przegrany", who: CLIENT, rejected: "client_project_closed" },
      { key: "client_after_deadline", label: "Wysłany po terminie", who: CLIENT, rejected: "client_after_deadline" },
      { key: "client_no_reason", label: "Nie podał powodu", who: CLIENT, rejected: "client_no_reason" },
    ],
  },
  {
    title: "Nie pasuje do wymagań",
    reasons: [
      { key: "missing_skill", label: "Brak kluczowej umiejętności", who: US_CLIENT, rejected: "Nie spełnia wymagań technicznych" },
      { key: "too_junior", label: "Za mało doświadczenia", who: US_CLIENT, rejected: "Brak doświadczenia" },
      { key: "overqualified", label: "Za wysoki poziom (overqualified)", who: US_CLIENT, rejected: "overqualified" },
      { key: "other_level_or_role", label: "Inny poziom lub inna rola", who: US_CLIENT, rejected: "other_level_or_role" },
      { key: "no_polish", label: "Brak polskiego", who: US_CLIENT, rejected: "no_polish" },
      { key: "weak_english", label: "Angielski za słaby", who: US_CLIENT, rejected: "weak_english" },
      { key: "culture", label: "Nie pasuje kulturowo", who: US_CLIENT, rejected: "Nie pasuje kulturowo" },
    ],
  },
  {
    title: "Warunki",
    reasons: [
      { key: "too_expensive", label: "Za droga", who: ALL, rejected: "Za wysokie oczekiwania finansowe", withdrawn: "salary_mismatch" },
      { key: "location_mode", label: "Lokalizacja lub tryb pracy", who: ALL, rejected: "work_mode_mismatch", withdrawn: "work_mode_mismatch" },
      { key: "outside_poland", label: "Mieszka poza Polską", who: US_CLIENT, rejected: "outside_poland" },
      { key: "contract_form", label: "Forma umowy (UoP / B2B)", who: ALL, rejected: "contract_form", withdrawn: "contract_form" },
      { key: "available_too_late", label: "Dostępna za późno / wypowiedzenie", who: ALL, rejected: "available_too_late", withdrawn: "available_too_late" },
    ],
  },
  {
    title: "Sprawa osoby",
    reasons: [
      { key: "not_looking", label: "Nie szuka pracy", who: US_CANDIDATE, rejected: "not_looking_for_work", withdrawn: "not_looking_for_work" },
      { key: "accepted_other_offer", label: "Przyjęła inną ofertę", who: ALL, rejected: "Zatrudniony gdzie indziej", withdrawn: "accepted_other_offer" },
      { key: "counter_offer", label: "Kontroferta od obecnego pracodawcy", who: CANDIDATE, withdrawn: "counter_offer" },
      { key: "lost_interest", label: "Straciła zainteresowanie / za długi proces", who: CANDIDATE, withdrawn: "lost_interest" },
      { key: "personal_reasons", label: "Powody osobiste", who: CANDIDATE, withdrawn: "personal_reasons" },
      { key: "no_answer", label: "Nie odbiera / brak kontaktu", who: US_CANDIDATE, rejected: "no_contact", withdrawn: "no_contact" },
      { key: "in_other_process", label: "Już u nas w innym procesie", who: ["recruiter"], rejected: "in_other_process" },
      { key: "client_employed", label: "Pracuje u klienta / zgłoszona przez inną firmę", who: US_CLIENT, rejected: "client_other_vendor" },
      { key: "client_refused", label: "Nie chce do tego klienta", who: US_CANDIDATE, rejected: "client_refused", withdrawn: "client_refused" },
      { key: "hm_already_interviewed", label: "Już po rozmowie u tego hiring managera", who: US_CLIENT, rejected: "hm_already_interviewed" },
    ],
  },
  {
    title: "Dane w bazie",
    reasons: [
      { key: "outdated_cv", label: "CV nieaktualne", who: ["recruiter"], rejected: "outdated_cv", earlyOnly: true },
      { key: "profile_mismatch", label: "Profil w bazie się nie zgadza", who: ["recruiter"], rejected: "profile_mismatch", earlyOnly: true },
      { key: "wrong_phone", label: "Błędny numer telefonu", who: ["recruiter"], rejected: "wrong_phone", earlyOnly: true },
    ],
  },
];

export const OTHER_CLOSE_REASON: CloseReason = {
  key: "other",
  label: "Inne — opisz",
  who: ALL,
  rejected: "Inne (rejected)",
  withdrawn: "Inne (withdrawn)",
};

const BY_KEY: ReadonlyMap<CloseReasonKey, CloseReason> = new Map(
  [...CLOSE_REASON_GROUPS.flatMap((g) => g.reasons), OTHER_CLOSE_REASON].map((r) => [r.key, r]),
);

export function closeReason(key: CloseReasonKey | null | undefined): CloseReason | undefined {
  return key ? BY_KEY.get(key) : undefined;
}

/** „Kto kończy?” okna → strona słownika. Delivery Lead mówi jak my. */
export function closeWhoFor(endedBy: "candidate" | "recruiter" | "delivery_lead" | "client"): CloseWho {
  if (endedBy === "candidate") return "candidate";
  if (endedBy === "client") return "client";
  return "recruiter";
}

/** Czy powód może wybrać ta strona na tym etapie. */
export function closeReasonFits(reason: CloseReason, who: CloseWho, early: boolean): boolean {
  return reason.who.includes(who) && (!reason.earlyOnly || early);
}

/**
 * Grupy okna dla tego, kto kończy, i etapu (`early` — „Nowi”/„Screening”).
 * „Inne” nie stoi w żadnej grupie: okno pokazuje je zawsze na końcu.
 */
export function closeReasonGroups(who: CloseWho, early: boolean): CloseReasonGroup[] {
  return CLOSE_REASON_GROUPS.map((g) => ({
    ...g,
    reasons: g.reasons.filter((r) => closeReasonFits(r, who, early)),
  })).filter((g) => g.reasons.length > 0);
}

/** Nazwa wiersza szablonu dla powodu i strony, która kończy. */
export function closeTemplateName(key: CloseReasonKey, who: CloseWho): string | undefined {
  const reason = BY_KEY.get(key);
  if (!reason) return undefined;
  return who === "candidate" ? reason.withdrawn : reason.rejected;
}

/**
 * Wiersz szablonu dla powodu słownika. Szablon bez tego wiersza (admin go
 * skasował, stary szablon) wraca do „Inne” — okno dopisze wtedy nazwę powodu
 * do opisu, żeby historia jej nie zgubiła.
 */
export function closeTemplateReason<T extends { name?: string; label: string }>(
  key: CloseReasonKey | null,
  who: CloseWho,
  reasons: readonly T[],
): T | undefined {
  if (!key) return undefined;
  const name = closeTemplateName(key, who);
  return (
    (name ? reasons.find((r) => r.name?.trim() === name) : undefined) ??
    reasons.find((r) => r.label.trim() === "Inne")
  );
}

/**
 * Lista wierszy szablonu w kolejności i z etykietami słownika — dla miejsc,
 * które wybierają wiersz szablonu wprost (panel DL, karta rozmowy u klienta).
 * Wiersze spoza słownika (dopisane przez admina) nie wchodzą; „Inne” na końcu.
 */
export function closeTemplateOptions<T extends { name?: string; label: string }>(
  reasons: readonly T[],
  who: CloseWho,
  early = false,
): T[] {
  const out: T[] = [];
  const taken = new Set<T>();
  for (const group of closeReasonGroups(who, early)) {
    for (const reason of group.reasons) {
      const name = closeTemplateName(reason.key, who);
      const row = name ? reasons.find((r) => r.name?.trim() === name) : undefined;
      if (!row || taken.has(row)) continue;
      taken.add(row);
      out.push({ ...row, label: reason.label });
    }
  }
  const other = reasons.find((r) => r.name?.trim() === closeTemplateName("other", who));
  if (other) out.push(other);
  return out;
}
