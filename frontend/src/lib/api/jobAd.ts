// Ogłoszenie rekrutacji do wklejenia na portale (Pracuj.pl, JustJoin.IT).
//
// Typy są lustrem kontraktu backendu (`/api/jobs/{id}/portal-ad`,
// `/api/job-ads/fixed-blocks`, `backend/app/schemas/job_ad.py`). Klucze zapytań
// są EKSPORTOWANYMI funkcjami: harness `/preview/job-ad` zasiewa cache tymi
// samymi funkcjami, więc zmiana klucza nie może się rozjechać z zasiewem.

import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";
import { SLOW_ENDPOINT_TIMEOUT_MS } from "@/lib/http-timeouts";

// ── Typy ─────────────────────────────────────────────────────────────────

export type AdLang = "pl" | "en";
export type AdTechLevel = "critical" | "must" | "nice";
export type AdSource = "ai" | "template";
export type AdSeverity = "block" | "advise";
export type AdPortal = "pracuj" | "jjit";

/** Portale w kolejności, w jakiej pokazuje je okno, sekcja i lista rekrutacji. */
export const AD_PORTALS: ReadonlyArray<{ key: AdPortal; label: string; short: string }> = [
  { key: "pracuj", label: "Pracuj.pl", short: "Pracuj" },
  { key: "jjit", label: "JustJoin.IT", short: "JJIT" },
];

/** Pola, które rekruter może poprawić ręcznie. */
export interface AdContent {
  title: string;
  lead: string;
  about: string;
  start: string;
  duration: string;
  /** Język pracy (np. „polski, angielski B2”) — nie język ogłoszenia. */
  language: string;
  responsibilities: string[];
  requirements: string[];
  nice_to_have: string[];
  offer: string[];
  /** Punkty z rekrutacji i stałego bloku ukryte w tym ogłoszeniu. */
  offer_hidden?: string[];
}

/** Ile własnych punktów „co oferujemy” przyjmuje serwer (`LIST_LIMITS`). */
export const OFFER_OWN_MAX = 6;

export type AdListKey = "responsibilities" | "requirements" | "nice_to_have" | "offer";
export type AdTextKey = "title" | "lead" | "about" | "start" | "duration" | "language";

export interface AdTechItem {
  name: string;
  level: AdTechLevel;
}

export interface AdRead {
  lang: AdLang;
  content: AdContent;
  tech: AdTechItem[];
  source: AdSource;
  generated_at: string | null;
  updated_at: string | null;
  /** Rekrutacja zmieniła się od przygotowania ogłoszenia. */
  stale: boolean;
}

export interface AdFact {
  key: string;
  label: string;
  value: string;
}

export interface AdReadinessItem {
  key: string;
  label: string;
  present: boolean;
}

export interface AdFinding {
  code: string;
  severity: AdSeverity;
  message: string;
  excerpt: string | null;
  field: string | null;
}

export type RenderedKind = "text" | "list" | "ordered";

export interface RenderedField {
  key: string;
  label: string;
  kind: RenderedKind;
  /** Zwykły tekst do schowka (lista = jedna pozycja w wierszu). */
  text: string;
  /** HTML do schowka — NIGDY do `dangerouslySetInnerHTML`. */
  html: string;
  items: string[];
  /** Pierwsze N pozycji pochodzi z pól rekrutacji. */
  auto_count: number;
  /** Ostatnie N pozycji to stały blok z Ustawień. */
  fixed_count: number;
  /** Punkty z rekrutacji / stałego bloku ukryte w tym ogłoszeniu. */
  hidden_auto?: string[];
  hidden_fixed?: string[];
}

export interface RenderedTech {
  name: string;
  level: number;
  label: string;
  source: AdTechLevel;
}

export interface RenderedSection {
  key: string;
  heading: string | null;
  kind: RenderedKind;
  text: string;
  items: string[];
  fixed_count: number;
}

export interface RenderedAd {
  title: string;
  pracuj: { fields: RenderedField[]; params: string[] };
  jjit: {
    form_fields: AdFact[];
    tech_stack: RenderedTech[];
    /** Technologie poza limitem portalu (10). */
    tech_overflow: number;
    sections: RenderedSection[];
    body_html: string;
    body_text: string;
  };
}

/** Aktywne ogłoszenie w wierszu listy rekrutacji (`ad_publications`). */
export interface JobAdPublicationBrief {
  portal: AdPortal;
  url: string | null;
  /** Zapisana treść jest inna niż w chwili oznaczenia publikacji. */
  outdated: boolean;
}

/** Stan portalu w oknie i w sekcji „Zespół i ogłoszenie”. */
export interface AdPublication extends JobAdPublicationBrief {
  published_at: string;
  published_by_name: string | null;
  /** Ustawione = zdjęte z portalu. */
  removed_at: string | null;
}

/**
 * Strona kariery rekrutacji (21.10.2026): `none` = nie ma, `live` = pokazuje
 * to ogłoszenie, `outdated` = działa, ale z inną treścią niż obecne ogłoszenie.
 */
export type AdCareerStatus = "none" | "live" | "outdated";

export interface AdCareerState {
  status: AdCareerStatus;
  /** Własny link osoby, a bez niego link z tablicy kariery. */
  url: string | null;
  published_at: string | null;
  published_by_name: string | null;
}

export const NO_CAREER_PAGE: AdCareerState = {
  status: "none",
  url: null,
  published_at: null,
  published_by_name: null,
};

/** Kanał ogłoszenia rekrutacji (przypomnienia mailem, 27.10.2026). */
export type AdChannel = "kariera" | "pracuj" | "jjit";

export const AD_CHANNEL_LABEL: Record<AdChannel, string> = {
  kariera: "Strona kariery",
  pracuj: "Pracuj.pl",
  jjit: "JustJoin.IT",
};

export interface AdChannelView {
  channel: AdChannel;
  /** `requested` = mail do opiekuna Pracuj.pl wyszedł, opiekun ma jeszcze czas. */
  state: "live" | "missing" | "skipped" | "requested";
  since: string | null;
  /** Brak robi osoba na ekranie (rekruter: strona kariery; DL: portale). */
  mine: boolean;
  owner_names: string[];
  skip_reason: string | null;
  skipped_by_name: string | null;
}

export interface AdReminders {
  channels: AdChannelView[];
  /** „Nie publikujemy” i „Przypomnij”: DL rekrutacji, Head of Recruitment, admin. */
  can_manage: boolean;
  recruiter_names: string[];
}

export interface AdRemindResult {
  sent_to: string[];
  /** Już dziś przypomniano — drugi mail tego dnia nie wychodzi. */
  already: string[];
}

/** Rekrutacja z brakiem, który robi osoba („Ogłoszenia do nadrobienia”). */
export interface MissingAdsItem {
  job_id: number;
  title: string;
  client: string | null;
  opened_at: string | null;
  /** Otwarta przed startem przypomnień — idzie mailem zbiorczym. */
  backlog: boolean;
  channels: AdChannelView[];
}

export const missingAdsQueryKey = ["job-ad", "missing"] as const;

export interface JobAdState {
  ad: AdRead | null;
  /** Strona kariery z tej samej treści. */
  career: AdCareerState;
  facts: AdFact[];
  readiness: AdReadinessItem[];
  findings: AdFinding[];
  rendered: RenderedAd | null;
  /** Ogłoszenie istnieje i nie ma znalezisk blokujących. */
  can_copy: boolean;
  /** Gdzie ogłoszenie wisi — także wiersze „zdjęte z portalu”. */
  publications: AdPublication[];
  /** Trzy kanały i kto je robi; `null` = rekrutacja zamknięta. */
  reminders: AdReminders | null;
  /** Ostatni mail do opiekuna Pracuj.pl (27.10.2026). */
  pracuj_request: PracujRequest | null;
}

/** Mail z ogłoszeniem do opiekuna Pracuj.pl wysłany z NEXUSA. */
export interface PracujRequest {
  sent_at: string;
  sent_by_name: string | null;
  to: string | null;
  /** Opiekun ma jeszcze czas — przypomnienia o Pracuj.pl milczą. */
  waiting: boolean;
}

export interface PracujMailRates {
  rate_from: number | null;
  rate_to: number | null;
}

/** Podgląd maila do opiekuna — skład z serwera, ten sam co przy wysyłce. */
export interface PracujMailPreview {
  to_name: string;
  to_email: string;
  /** `ready` = wyśle · `missing` = skrzynka niepodłączona · `reconnect` = połącz ponownie. */
  mailbox: "ready" | "missing" | "reconnect";
  from_address: string | null;
  subject: string;
  body_text: string;
  /** Stawka, której nie wyślemy (pusta, odwrócona) — komunikat do pola. */
  rate_error: string | null;
}

/** Otwarta rekrutacja bez strony kariery — kolejka „Opublikuj i następna” (21.10.2026). */
export interface CareerQueueItem {
  job_id: number;
  title: string;
  city: string | null;
  remote_policy: string | null;
  delivery_lead_name: string | null;
  opened_at: string | null;
  /** `ready` = treść czeka, `template` = złożona bez modelu, `missing` = brak treści. */
  ad: "ready" | "template" | "missing";
}

export type CareerQueueScope = "mine" | "all";

export interface CareerQueue {
  scope: CareerQueueScope;
  mine_count: number;
  all_count: number;
  items: CareerQueueItem[];
}

export type TitleSuffix = "kmx" | "km" | "none";

export interface FixedLangBlocks {
  offer: string[];
  process: string[];
  about: string;
}

export interface PracujCaretaker {
  /** Imię do powitania („Dzień dobry Nicola,”); puste = „Dzień dobry,”. */
  name: string;
  email: string;
}

export interface FixedBlocks {
  title_suffix: TitleSuffix;
  pl: FixedLangBlocks;
  en: FixedLangBlocks;
  /** Opiekun konta Pracuj.pl — adresat „Wyślij do Pracuj.pl” (27.10.2026). */
  pracuj_caretaker: PracujCaretaker;
}

// ── Klucze zapytań ───────────────────────────────────────────────────────

export const jobAdQueryKey = (jobId: number) => ["job-ad", jobId] as const;
export const pracujMailPreviewQueryKey = (jobId: number, rates: PracujMailRates) =>
  ["job-ad", jobId, "pracuj-mail", rates.rate_from, rates.rate_to] as const;
export const jobAdFixedBlocksQueryKey = () => ["job-ad", "fixed-blocks"] as const;
export const careerQueueQueryKey = (scope: CareerQueueScope, limit?: number) =>
  ["job-ad", "career-queue", scope, limit ?? "all"] as const;

// ── Klient ───────────────────────────────────────────────────────────────

function normalize(data: unknown): JobAdState {
  const d = (data ?? {}) as Partial<JobAdState>;
  return {
    ad: d.ad ?? null,
    career: d.career ?? NO_CAREER_PAGE,
    facts: Array.isArray(d.facts) ? d.facts : [],
    readiness: Array.isArray(d.readiness) ? d.readiness : [],
    findings: Array.isArray(d.findings) ? d.findings : [],
    rendered: d.rendered ?? null,
    can_copy: d.can_copy === true,
    publications: Array.isArray(d.publications) ? d.publications : [],
    reminders:
      d.reminders && Array.isArray(d.reminders.channels)
        ? {
            channels: d.reminders.channels,
            can_manage: d.reminders.can_manage === true,
            recruiter_names: Array.isArray(d.reminders.recruiter_names)
              ? d.reminders.recruiter_names
              : [],
          }
        : null,
    pracuj_request: d.pracuj_request ?? null,
  };
}

export const jobAdApi = {
  get: async (jobId: number): Promise<JobAdState> => {
    const res = await api.get(`/api/jobs/${jobId}/portal-ad`);
    return normalize(res.data);
  },
  /**
   * Układa treść od nowa (model albo złożenie z pól rekrutacji) i ją zapisuje.
   * `expectedUpdatedAt` — wersja z ekranu; inna w bazie = 409 `job_ad_changed`.
   */
  generate: async (
    jobId: number,
    lang: AdLang,
    expectedUpdatedAt: string | null = null,
  ): Promise<JobAdState> => {
    const res = await api.post(
      `/api/jobs/${jobId}/portal-ad/generate`,
      { lang, expected_updated_at: expectedUpdatedAt },
      { timeout: SLOW_ENDPOINT_TIMEOUT_MS },
    );
    return normalize(res.data);
  },
  save: async (
    jobId: number,
    input: {
      content: AdContent;
      tech: AdTechItem[];
      /** `updated_at` wersji z ekranu — inna w bazie = 409 `job_ad_changed`. */
      expected_updated_at?: string | null;
    },
  ): Promise<JobAdState> => {
    const res = await api.put(`/api/jobs/${jobId}/portal-ad`, input);
    return normalize(res.data);
  },
  /**
   * „Wisi na portalu”. Przy aktywnym oznaczeniu samo wywołanie zmienia tylko
   * link; `contentUpdated` = „zaktualizowane na portalu” (gasi „do aktualizacji”).
   */
  markPublished: async (
    jobId: number,
    portal: AdPortal,
    url: string | null,
    contentUpdated = false,
  ): Promise<JobAdState> => {
    const res = await api.put(`/api/jobs/${jobId}/portal-ad/publications/${portal}`, {
      url,
      content_updated: contentUpdated,
    });
    return normalize(res.data);
  },
  /**
   * „Opublikuj na stronie” (21.10.2026): treść ogłoszenia trafia na stronę
   * kariery i od razu jest zatwierdzona. `expectedUpdatedAt` — wersja z ekranu.
   */
  publishCareer: async (
    jobId: number,
    expectedUpdatedAt: string | null = null,
  ): Promise<JobAdState> => {
    const res = await api.post(`/api/jobs/${jobId}/portal-ad/career`, {
      expected_updated_at: expectedUpdatedAt,
    });
    return normalize(res.data);
  },
  /** „Zdjęte z portalu” — wiersz zostaje jako ślad. */
  markRemoved: async (jobId: number, portal: AdPortal): Promise<JobAdState> => {
    const res = await api.delete(`/api/jobs/${jobId}/portal-ad/publications/${portal}`);
    return normalize(res.data);
  },
  /** `limit: 0` = same liczby (przycisk na liście rekrutacji). */
  careerQueue: async (scope: CareerQueueScope, limit?: number): Promise<CareerQueue> => {
    const res = await api.get<CareerQueue>("/api/job-ads/career-queue", {
      params: limit == null ? { scope } : { scope, limit },
    });
    return {
      scope: res.data?.scope ?? scope,
      mine_count: res.data?.mine_count ?? 0,
      all_count: res.data?.all_count ?? 0,
      items: Array.isArray(res.data?.items) ? res.data.items : [],
    };
  },
  /** „Nie publikujemy tej rekrutacji na …” z powodem (DL, HoR, admin). */
  skipChannel: async (
    jobId: number,
    channel: AdChannel,
    reason: string,
  ): Promise<JobAdState> => {
    const res = await api.put(`/api/jobs/${jobId}/portal-ad/skips/${channel}`, { reason });
    return normalize(res.data);
  },
  /** Cofnięcie „nie publikujemy” — przypomnienia o kanale wracają. */
  unskipChannel: async (jobId: number, channel: AdChannel): Promise<JobAdState> => {
    const res = await api.delete(`/api/jobs/${jobId}/portal-ad/skips/${channel}`);
    return normalize(res.data);
  },
  /** DL prosi rekruterów o stronę kariery — mail od razu, raz dziennie. */
  remindRecruiters: async (jobId: number): Promise<AdRemindResult> => {
    const res = await api.post<AdRemindResult>(`/api/jobs/${jobId}/portal-ad/remind`);
    return {
      sent_to: Array.isArray(res.data?.sent_to) ? res.data.sent_to : [],
      already: Array.isArray(res.data?.already) ? res.data.already : [],
    };
  },
  /** Rekrutacje z brakiem, który robi osoba — od najnowszej. */
  missing: async (): Promise<MissingAdsItem[]> => {
    const res = await api.get<{ items?: MissingAdsItem[] }>("/api/job-ads/missing");
    return Array.isArray(res.data?.items) ? res.data.items : [];
  },
  /** Podgląd maila do opiekuna Pracuj.pl (DL, HoR, admin) — nic nie zapisuje. */
  previewPracujMail: async (
    jobId: number,
    rates: PracujMailRates,
  ): Promise<PracujMailPreview> => {
    const res = await api.post<PracujMailPreview>(
      `/api/jobs/${jobId}/portal-ad/pracuj-mail/preview`,
      rates,
    );
    return res.data;
  },
  /**
   * Mail z ogłoszeniem do opiekuna Pracuj.pl ze skrzynki osoby. Ten sam
   * `clientRequestId` przy ponowieniu = ten sam mail, bez drugiej wysyłki.
   */
  sendPracujMail: async (
    jobId: number,
    input: PracujMailRates & {
      expected_updated_at: string | null;
      client_request_id: string;
    },
  ): Promise<JobAdState> => {
    const res = await api.post(`/api/jobs/${jobId}/portal-ad/pracuj-mail`, input);
    return normalize(res.data);
  },
  getFixedBlocks: async (): Promise<FixedBlocks> => {
    const res = await api.get<FixedBlocks>("/api/job-ads/fixed-blocks");
    return res.data;
  },
  saveFixedBlocks: async (input: FixedBlocks): Promise<FixedBlocks> => {
    const res = await api.put<FixedBlocks>("/api/job-ads/fixed-blocks", input);
    return res.data;
  },
};

// ── Hooki ────────────────────────────────────────────────────────────────

export function useJobAd(jobId: number | null, enabled = true) {
  return useQuery({
    queryKey: jobAdQueryKey(jobId ?? 0),
    queryFn: () => jobAdApi.get(jobId as number),
    enabled: enabled && jobId != null && jobId > 0,
  });
}

// ── Czyste pomocniki ─────────────────────────────────────────────────────

export function blockingFindings(findings: AdFinding[]): AdFinding[] {
  return findings.filter((f) => f.severity === "block");
}

export function advisoryFindings(findings: AdFinding[]): AdFinding[] {
  return findings.filter((f) => f.severity === "advise");
}

/** Oznaczenie portalu, które nadal obowiązuje (nie „zdjęte”). */
export function activePublication(
  publications: readonly AdPublication[],
  portal: AdPortal,
): AdPublication | null {
  return publications.find((item) => item.portal === portal && !item.removed_at) ?? null;
}

// RocketJobs połączył się z JustJoin.IT — ogłoszenie wisi też pod rocketjobs.pl.
const PORTAL_DOMAINS: Record<AdPortal, readonly string[]> = {
  pracuj: ["pracuj.pl"],
  jjit: ["justjoin.it", "rocketjobs.pl"],
};

/**
 * Adres ogłoszenia do odnośnika — tak, jak przeczyta go przeglądarka; `null` =
 * odnośnika nie pokazujemy. Serwer waliduje link przy zapisie, ale to parser
 * przeglądarki decyduje, dokąd klik prowadzi („https://obca.strona\.pracuj.pl”
 * to dla niej obca strona), więc przy samym `href` sprawdzamy jeszcze raz.
 */
export function portalAdHref(portal: AdPortal, url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    const onPortal = PORTAL_DOMAINS[portal].some(
      (domain) => parsed.hostname === domain || parsed.hostname.endsWith(`.${domain}`),
    );
    const web = parsed.protocol === "https:" || parsed.protocol === "http:";
    return web && onPortal ? parsed.href : null;
  } catch {
    return null;
  }
}

/** Lista z pola tekstowego: jedna pozycja w wierszu, bez pustych. */
export function linesToItems(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

/** Zapis albo przygotowanie odrzucone, bo ktoś w międzyczasie zmienił ogłoszenie (409). */
export function isAdChangedError(error: unknown): boolean {
  const response = (error as { response?: { status?: unknown; data?: unknown } })?.response;
  if (response?.status !== 409) return false;
  const detail = (response.data as { detail?: unknown } | null)?.detail;
  return (
    !!detail &&
    typeof detail === "object" &&
    (detail as { code?: unknown }).code === "job_ad_changed"
  );
}
