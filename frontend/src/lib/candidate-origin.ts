/**
 * „Skąd osoba jest w bazie” — sposób dodania i kto dodał (prośba rekrutera
 * 19.10.2026: „brakuje opcji, żeby sprawdzić, kto dodał kandydata do bazy,
 * np. manualnie albo z indywidualnego linku na LinkedInie”).
 *
 * Dane liczy serwer: `added_via` (etykieta sposobu, `candidate_added_date.py`),
 * `created_by_user` (twórca rekordu) i — tylko w szczegółach osoby —
 * `invite_source` (zgłoszenie przez link: rodzaj linku, właściciel, utm).
 * Ten moduł tylko wybiera, co powiedzieć; niczego nie zgaduje.
 */

export interface InviteSourceBrief {
  label?: string | null;
  created_by_name?: string | null;
  applied_at?: string | null;
  previous_created_by_name?: string | null;
  link_kind?: "job" | "recruiter" | null;
  utm_source?: string | null;
  /** Osoba była już w bazie — zgłoszenie nie utworzyło rekordu. */
  was_duplicate?: boolean | null;
}

export interface CandidateOriginInput {
  added_via?: string | null;
  created_by_user?: { id?: number; name?: string | null } | null;
  invite_source?: InviteSourceBrief | null;
}

export interface CandidateOrigin {
  /** „Link rekrutera”, „Link do rekrutacji”, „Wtyczka LinkedIn”, „CV upload”… */
  how: string | null;
  /** Kto dodał — przy linku właściciel linku; `null`, gdy nie wiemy. */
  by: string | null;
  /** Osoba sama wypełniła formularz z czyjegoś linku. */
  viaLink: boolean;
  /** Nazwa linku nadana przez rekrutera („Post na LinkedIn”). */
  linkLabel: string | null;
  /** Skąd weszła na formularz — `utm_source` z adresu. */
  entryFrom: string | null;
  /** Rekruter, od którego link przejął osobę. */
  previousBy: string | null;
  /** Późniejsze zgłoszenie osoby z bazy przez link („Link rekrutera · Jan K.”). */
  laterApply: string | null;
}

const LINK_KIND_LABEL: Record<"job" | "recruiter", string> = {
  recruiter: "Link rekrutera",
  job: "Link do rekrutacji",
};

const UTM_LABEL: Record<string, string> = {
  linkedin: "LinkedIn",
  facebook: "Facebook",
  instagram: "Instagram",
  justjoinit: "Just Join IT",
  pracuj: "Pracuj.pl",
  google: "Google",
};

function clean(value: string | null | undefined): string | null {
  const text = (value ?? "").trim();
  // API pisze „—”, gdy nie zna rekrutera — to brak osoby, nie nazwisko.
  return text && text !== "—" ? text : null;
}

function entryLabel(utm: string | null | undefined): string | null {
  const text = clean(utm);
  if (!text) return null;
  return UTM_LABEL[text.toLowerCase()] ?? text;
}

export function candidateOrigin(candidate: CandidateOriginInput | null | undefined): CandidateOrigin {
  const invite = candidate?.invite_source ?? null;
  const linkHow = invite
    ? invite.link_kind
      ? LINK_KIND_LABEL[invite.link_kind]
      : "Formularz aplikacyjny"
    : null;
  if (invite && !invite.was_duplicate) {
    return {
      how: linkHow,
      by: clean(invite.created_by_name) ?? clean(candidate?.created_by_user?.name),
      viaLink: true,
      linkLabel: clean(invite.label),
      entryFrom: entryLabel(invite.utm_source),
      previousBy: clean(invite.previous_created_by_name),
      laterApply: null,
    };
  }
  // Zgłoszenie osoby, która już była w bazie, nie mówi, kto ją DODAŁ —
  // rekord i jego twórca zostają; link to osobna informacja.
  const laterOwner = invite ? clean(invite.created_by_name) : null;
  return {
    how: clean(candidate?.added_via),
    by: clean(candidate?.created_by_user?.name),
    viaLink: false,
    linkLabel: null,
    entryFrom: null,
    previousBy: null,
    laterApply: linkHow ? [linkHow, laterOwner].filter(Boolean).join(" · ") : null,
  };
}

/**
 * Jedna linia: „Link rekrutera · Jan Kowalski”, „CV upload · dodał(a) Anna”.
 * Przy linku osoba zgłosiła się sama, więc bez „dodał(a)”.
 */
export function originSummary(origin: CandidateOrigin): string | null {
  const by = origin.by ? (origin.viaLink ? origin.by : `dodał(a) ${origin.by}`) : null;
  return [origin.how, by].filter(Boolean).join(" · ") || null;
}
