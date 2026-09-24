/**
 * Biblioteka raportów Insights (przebudowa 24.09.2026).
 *
 * Widoki (Rywalizacja, Mój miesiąc, Zespół, Firma) mają po kilka liczb
 * i jedno zdanie. Wszystko inne żyje tutaj — każdy raport na całą stronę,
 * z pytaniem, na które odpowiada, w nagłówku. Nic, co było w Insights przed
 * przebudową, nie znika: rejestr jest jedynym miejscem, które mówi, gdzie
 * trafił dawny blok.
 *
 * Moduł jest czysty (bez komponentów) — mapę id → komponent trzyma
 * `components/insights/views/RaportyView.tsx`.
 */

import type { InsightsPeriodParams } from "@/lib/insights-api";
import { hasSectionAccess } from "@/lib/section-access";
import { hasAnalyticsCapability, hasRole, type User } from "@/store/auth";

export type ReportId =
  | "lejek-etapy"
  | "czas-konwersje"
  | "placementy"
  | "kompetencje"
  | "aktywnosc-zespolu"
  | "obciazenie"
  | "prepy"
  | "bez-ruchu"
  | "doplyw"
  | "portfele-dl"
  | "ranking-klientow"
  | "rok-do-roku"
  | "hall-of-fame"
  | "sciezka";

export type ReportGroup =
  | "Rekrutacja"
  | "Zespół"
  | "Dopływ kandydatów"
  | "Klienci i trend"
  | "Rywalizacja";

type ReportUser = User;

export interface ReportDef {
  id: ReportId;
  group: ReportGroup;
  title: string;
  /** Pytanie, na które raport odpowiada — nagłówek strony raportu. */
  question: string;
  /** Okno czasu opisane słowami (pigułka na karcie). */
  window: string;
  /** Domyślny okres paska; `null` = raport bez paska okresu. */
  defaultPeriod: InsightsPeriodParams | null;
  /** Dopisek na karcie, np. „tylko admin i HoR" albo „bez kwot". */
  note?: string;
  /** Kto widzi raport. Brak = każdy, kto widzi Insights. */
  visible?: (user: ReportUser) => boolean;
}

const MONTH_CLOSED: InsightsPeriodParams = { period: "month", offset: -1 };

const isLeader = (user: ReportUser) =>
  hasRole(user, "admin", "head_of_recruitment");
// Imienne wyniki cudzej pracy — ta sama capability co `/api/insights/team/*`.
const seesTeam = (user: ReportUser) =>
  hasRole(user, "admin") || hasAnalyticsCapability(user, "view_team_kpi");
// Pieniądze firmy: tylko admin i Finanse (decyzja Artura 24.09.2026).
const seesMoney = (user: ReportUser) => hasRole(user, "admin", "finance");

export const REPORTS: readonly ReportDef[] = [
  {
    id: "lejek-etapy",
    group: "Rekrutacja",
    title: "Lejek po etapach",
    question:
      "Ile osób doszło do każdego etapu i odznaki Tablicy, a ile stoi tam teraz?",
    window: "miesiąc",
    defaultPeriod: MONTH_CLOSED,
  },
  {
    id: "czas-konwersje",
    group: "Rekrutacja",
    title: "Czas i konwersje",
    question: "Ile trwa droga do zatrudnienia i jaki procent przechodzi dalej?",
    window: "miesiąc",
    defaultPeriod: MONTH_CLOSED,
  },
  {
    id: "placementy",
    group: "Rekrutacja",
    title: "Analiza placementów",
    question: "U jakich klientów i przez kogo były placementy?",
    window: "kwartał",
    defaultPeriod: { period: "quarter", offset: 0 },
  },
  {
    id: "kompetencje",
    group: "Rekrutacja",
    title: "Kompetencje w toku",
    question: "Jakich profili szukamy teraz i na jakim są etapie?",
    window: "stan na dziś",
    defaultPeriod: null,
  },
  {
    id: "aktywnosc-zespolu",
    group: "Zespół",
    title: "Aktywność zespołu",
    question:
      "Kto ile zweryfikował, wysłał i zatrudnił — i kto ile dodał kandydatów, screeningów i rozmów?",
    window: "miesiąc",
    defaultPeriod: MONTH_CLOSED,
  },
  {
    id: "obciazenie",
    group: "Zespół",
    title: "Obłożenie i zastępstwa",
    question: "Kto ma za dużo pracy i kto kogo zastępuje?",
    window: "stan na dziś",
    defaultPeriod: null,
    note: "admin i Head of Recruitment",
    visible: (user) => isLeader(user) && hasSectionAccess(user, "pipeline"),
  },
  {
    id: "prepy",
    group: "Zespół",
    title: "Jakość prepów",
    question:
      "Czy prepy przed rozmową u klienta pokrywają must-have i pytania klienta?",
    window: "90 dni",
    defaultPeriod: null,
    note: "admin i Head of Recruitment",
    visible: (user) => isLeader(user) && hasSectionAccess(user, "pipeline"),
  },
  {
    id: "bez-ruchu",
    group: "Zespół",
    title: "Rekrutacje bez ruchu",
    question: "Które opublikowane rekrutacje stoją od 14 dni i kto je prowadzi?",
    window: "stan na dziś",
    defaultPeriod: null,
    visible: seesTeam,
  },
  {
    id: "doplyw",
    group: "Dopływ kandydatów",
    title: "Źródła, portale i linki",
    question: "Skąd przychodzą kandydaci i które źródło kończy się placementem?",
    window: "7 / 30 / 90 dni",
    defaultPeriod: null,
  },
  {
    id: "portfele-dl",
    group: "Klienci i trend",
    title: "Portfele Delivery Leadów",
    question: "Jak idą rekrutacje i hit ratio u klientów każdego DL?",
    window: "rok",
    defaultPeriod: { period: "year", offset: 0 },
    note: "bez kwot",
  },
  {
    id: "ranking-klientow",
    group: "Klienci i trend",
    title: "Ranking klientów",
    question: "Który klient ile daje przychodu i marży miesięcznie?",
    window: "kwartał",
    defaultPeriod: { period: "quarter", offset: 0 },
    note: "admin i Finanse",
    visible: seesMoney,
  },
  {
    id: "rok-do-roku",
    group: "Klienci i trend",
    title: "Rok do roku",
    question: "Jak wyglądają placementy, hit ratio i zejścia miesiąc po miesiącu w kolejnych latach?",
    window: "pełne lata",
    defaultPeriod: null,
    note: "kwoty tylko admin i Finanse",
  },
  {
    id: "hall-of-fame",
    group: "Rywalizacja",
    title: "Hall of Fame i historia konkursów",
    question: "Kto ma najwięcej placementów w historii i kto wygrywał konkursy?",
    window: "cała historia",
    defaultPeriod: null,
  },
  {
    id: "sciezka",
    group: "Rywalizacja",
    title: "Ścieżka rozwoju",
    question: "Kto jest na jakim poziomie i ile brakuje mu do awansu?",
    window: "6 i 12 miesięcy",
    defaultPeriod: null,
  },
];

export const REPORT_GROUPS: readonly ReportGroup[] = [
  "Rekrutacja",
  "Zespół",
  "Dopływ kandydatów",
  "Klienci i trend",
  "Rywalizacja",
];

export function isReportId(value: string | null | undefined): value is ReportId {
  return REPORTS.some((r) => r.id === value);
}

export function reportById(id: ReportId): ReportDef {
  const found = REPORTS.find((r) => r.id === id);
  if (!found) throw new Error(`Nieznany raport: ${id}`);
  return found;
}

/**
 * Raporty widoczne dla użytkownika. Przed hydracją auth (`user === null`)
 * zwraca wszystkie: brak użytkownika to „jeszcze nie wiemy", nie „nie wolno"
 * — inaczej pierwsze wejście w link do raportu przepisałoby adres na listę.
 */
export function visibleReports(user: ReportUser | null): ReportDef[] {
  return REPORTS.filter((r) => !user || !r.visible || r.visible(user));
}

/** Adres raportu na całą stronę. */
export function reportHref(id: ReportId): string {
  return `/insights?tab=raporty&report=${id}`;
}
