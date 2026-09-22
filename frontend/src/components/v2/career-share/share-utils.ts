// Czyste pomocniki okna „Udostępnij rekrutację" — testowalne bez montowania.

import type {
  ExpiryChoice,
  InviteLink,
  InviteLinkStatus,
  PublicJobParams,
  PublicProfileFinding,
  PublicProfileStatus,
} from "@/lib/api/careerLinks";

export const DEFAULT_CAREER_HOST = "kariera.dynaminds.pl";

export const EXPIRY_OPTIONS: { value: ExpiryChoice; label: string }[] = [
  { value: "none", label: "Do zamknięcia rekrutacji" },
  { value: "7", label: "7 dni" },
  { value: "14", label: "14 dni" },
  { value: "30", label: "30 dni" },
  { value: "90", label: "90 dni" },
];

export function expiryToDays(choice: ExpiryChoice): 7 | 14 | 30 | 90 | null {
  return choice === "none" ? null : (Number(choice) as 7 | 14 | 30 | 90);
}

export const INVITE_STATUS_LABEL: Record<InviteLinkStatus, string> = {
  active: "Aktywny",
  used: "Używany",
  revoked: "Wycofany",
  expired: "Wygasł",
};

export const INVITE_STATUS_VARIANT: Record<
  InviteLinkStatus,
  "success" | "soft" | "neutral" | "danger"
> = {
  active: "success",
  used: "soft",
  revoked: "danger",
  expired: "neutral",
};

export const PROFILE_STATUS_LABEL: Record<PublicProfileStatus, string> = {
  none: "Brak opisu",
  draft: "Szkic — niezatwierdzony",
  approved: "Zatwierdzony",
};

export const PROFILE_STATUS_VARIANT: Record<
  PublicProfileStatus,
  "neutral" | "warning" | "success"
> = {
  none: "neutral",
  draft: "warning",
  approved: "success",
};

/** Adres publiczny linku — nowe linki mają `public_url`, stare tylko `url`. */
export function linkUrl(link: Pick<InviteLink, "url" | "public_url">): string {
  return link.public_url || link.url;
}

export function isLinkLive(link: InviteLink): boolean {
  return !link.revoked && (link.status === "active" || link.status === "used");
}

/** Aktywny link tej osoby do tej rekrutacji albo `null`. */
export function activeLinkForJob(
  links: InviteLink[],
  jobId: number | null,
): InviteLink | null {
  if (jobId == null) return null;
  return (
    links.find(
      (l) => l.job?.id === jobId && (l.kind ?? "job") === "job" && isLinkLive(l),
    ) ?? null
  );
}

/** „kariera.dynaminds.pl" z pełnego adresu; fallback na domyślny host. */
export function hostFromUrl(url: string | null | undefined): string {
  if (!url) return DEFAULT_CAREER_HOST;
  try {
    return new URL(url).host || DEFAULT_CAREER_HOST;
  } catch {
    return DEFAULT_CAREER_HOST;
  }
}

/** Reguła sluga z backendu: a-z0-9 i myślnik, 3–40 znaków, bez myślnika na końcach. */
export function isSlugFormatValid(slug: string): boolean {
  return /^[a-z0-9](?:[a-z0-9-]{1,38})[a-z0-9]$/.test(slug);
}

export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("pl-PL", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

// ── Kontrola przed publikacją ────────────────────────────────────────────

export interface FindingCategory {
  key: "client" | "money" | "contact";
  codes: string[];
  okLabel: string;
  fixHint: string;
}

export const FINDING_CATEGORIES: FindingCategory[] = [
  {
    key: "client",
    codes: ["client_name"],
    okLabel: "Brak nazwy klienta i jego aliasów",
    fixHint: "nazwę klienta",
  },
  {
    key: "money",
    codes: ["money"],
    okLabel: "Brak kwot i stawek",
    fixHint: "kwotę",
  },
  {
    key: "contact",
    codes: ["contact", "person_name"],
    okLabel: "Brak danych kontaktowych i nazwisk",
    fixHint: "dane kontaktowe i nazwiska",
  },
];

export function categoryOf(code: string): FindingCategory {
  return (
    FINDING_CATEGORIES.find((c) => c.codes.includes(code)) ??
    FINDING_CATEGORIES[2]
  );
}

/**
 * Znaleziska, które nadal dotyczą bieżącej treści. Serwer sprawdza zapisany
 * tekst; gdy rekruter usunie wskazany fragment, wiersz znika od razu (pełną
 * kontrolę i tak robi serwer przy zatwierdzeniu). Znalezisko bez fragmentu
 * zostaje zawsze.
 */
export function liveFindings(
  findings: PublicProfileFinding[],
  text: string,
): PublicProfileFinding[] {
  const haystack = text.toLowerCase();
  return findings.filter(
    (f) => !f.excerpt || haystack.includes(f.excerpt.toLowerCase()),
  );
}

/**
 * Usuwa fragment z tekstu i sprząta miejsce sklejenia (spacje, zdublowaną
 * interpunkcję) — tylko w miejscu cięcia, reszta tekstu zostaje nietknięta.
 */
export function removeExcerpt(text: string, excerpt: string): string {
  const idx = text.toLowerCase().indexOf(excerpt.toLowerCase());
  if (idx < 0) return text;
  const left = text.slice(0, idx).replace(/[ \t]+$/, "");
  let right = text.slice(idx + excerpt.length).replace(/^[ \t]+/, "");
  if (/^[.,;:!?]/.test(right) && (left === "" || /[.,;:!?]$/.test(left))) {
    right = right.slice(1).replace(/^[ \t]+/, "");
  }
  const needsSpace =
    left !== "" && right !== "" && !/\n$/.test(left) && !/^[\n.,;:!?]/.test(right);
  return `${left}${needsSpace ? " " : ""}${right}`.trim();
}

export function approveBlockedReason(findings: PublicProfileFinding[]): string {
  const cats = Array.from(new Set(findings.map((f) => categoryOf(f.code).key)));
  if (cats.length === 1) {
    const cat = FINDING_CATEGORIES.find((c) => c.key === cats[0]);
    return `Usuń ${cat?.fixHint ?? "oznaczone fragmenty"} z opisu, aby zatwierdzić.`;
  }
  return "Usuń oznaczone fragmenty z opisu, aby zatwierdzić.";
}

// ── Podgląd posta ────────────────────────────────────────────────────────

const REMOTE_LABEL: Record<string, string> = {
  remote: "zdalnie",
  hybrid: "hybryda",
  onsite: "stacjonarnie",
};

/** „[warszawa · hybryda · b2b · senior]" z parametrów podglądu. */
export function paramsTagline(params: PublicJobParams | null | undefined): string | null {
  if (!params) return null;
  const parts = [
    params.city,
    params.remote_policy ? REMOTE_LABEL[params.remote_policy] : null,
    params.contract,
    params.seniority,
  ]
    .filter((p): p is string => !!p && p.trim() !== "")
    .map((p) => p.toLowerCase());
  return parts.length ? `[${parts.join(" · ")}]` : null;
}

/** „senior-java-developer" dla komendy w podglądzie. */
export function slugifyTitle(title: string): string {
  return title
    .toLowerCase()
    .normalize("NFKD")
    .replace(/ł/g, "l")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
}
