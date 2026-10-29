"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { clientReferenceParts } from "@/lib/job-names";
import { cn } from "@/lib/utils";

export const SEGMENT_LABELS: Record<string, string> = {
  "talent-radar": "Talent Radar",
  "": "Dashboard",
  candidates: "Kandydaci",
  jobs: "Rekrutacje",
  clients: "Klienci",
  contacts: "Kontakty",
  contracts: "Kontrakty",
  wypis: "Wypis",
  talents: "Talenty",
  analytics: "Analityka",
  reports: "Raporty",
  calendar: "Kalendarz",
  // Sprzedaż (Atlas → NEXUS, 26.10.2026).
  sales: "Sprzedaż",
  companies: "Firmy",
  opportunities: "Szanse",
  tasks: "Zadania",
  leads: "Leady",
  summary: "Podsumowanie",
  duplicates: "Duplikaty",
  // „Ludzie w NEXUSIE” (16.10.2026).
  "my-time": "Mój czas",
  people: "Ludzie",
  equipment: "Sprzęt",
  hr: "Kadry",
  approvals: "Akceptacje",
  consents: "Moje zgody",
  cases: "Sprawy",
  payroll: "Płace",
  structure: "Struktura",
  team: "Mój zespół",
  offboarding: "Odejście",
  care: "Opieka",
  protocol: "Protokół",
  settings: "Ustawienia",
  templates: "Szablony email",
  admin: "Admin",
  profile: "Profil",
  diagnostics: "Diagnostyka",
  v2: "UI Showcase",
  pipeline: "Pipeline",
  scoring: "Ranking kandydatów",
  "prep-review": "Ocena prepów",
  "pipeline-templates": "Procesy",
  "contract-templates": "Wzory umów",
  compare: "Porównanie",
  manager: "Panel managera",
  // UAT M01-B09 / M03-B09 / M11-B08 — segmenty, które okruszki pokazywały
  // surowo („applications", „pending-veri…"). Nazwy jak w sidebarze i na
  // kafelkach Ustawień.
  dashboard: "Dashboard",
  "delivery-lead": "Delivery Lead",
  "head-of-recruitment": "Head of Recruitment",
  recruiter: "Rekruter",
  applications: "Zgłoszenia",
  sourcing: "Sourcing",
  marketplace: "Targ / Dostępni",
  "bulk-import": "Masowy import CV",
  search: "Wyszukiwanie",
  "contact-queue": "Do przedzwonienia",
  prep: "Przygotowanie do rozmowy",
  "cv-generator": "Generator CV",
  "b2b-generator": "Generator Umów B2B",
  new: "Nowy",
  "my-clients": "Panel klientów",
  "my-relationships": "Moje relacje",
  // 28.10.2026: /departed-care — kandydaci po osobach, które odeszły (DL).
  "departed-care": "Po osobach, które odeszły",
  "order-mail": "Zamówienia z maila",
  insights: "Insights",
  // 23.10.2026: /insights/autofill — „Jakość podpowiedzi systemu”.
  autofill: "Jakość podpowiedzi systemu",
  finance: "Finanse",
  help: "Pomoc",
  onboarding: "Wprowadzenie",
  upload: "Wgrywanie danych",
  ai: "Koszty AI",
  "api-integration": "Integracja z API",
  "api-keys": "Klucze API",
  extension: "Wtyczka LinkedIn",
  wtyczka: "Wtyczka LinkedIn",
  connect: "Połącz",
  "linkedin-extension": "Wtyczka LinkedIn",
  chats: "Audyt czatów",
  "client-portfolio-preview": "Podgląd importu klientów",
  "clients-overview": "Przegląd klientów",
  "cv-rules": "Reguły CV klientów",
  "hr-import": "Import z Compassa",
  "qc-quality": "Jakość QC",
  dictionaries: "Listy wyboru",
  "entity-fields": "Dodatkowe pola",
  "hiring-managers": "Top hiring managers",
  "rate-benchmarks": "Stawki rynkowe",
  "team-structure": "Zespół rekrutacji",
  // Trasy z 23–24.09.2026 (audyt 24.09) — nazwy jak w menu, na kafelkach
  // Ustawień i w nagłówkach stron. Nową stronę dopisz tutaj: test
  // „każdy stały segment…" czyta katalog `app/` i odrzuca slug bez nazwy.
  "403": "Brak dostępu",
  academy: "Akademia",
  "b2b-register-import": "Rejestr umów z Excela",
  "contract-docs-sharepoint": "Dokumenty kontraktów z SharePointa",
  "competence-team": "Kategorie kompetencji",
  contractors: "Kontraktorzy",
  "kpi-targets": "Cele KPI",
  nowosci: "Nowości — kto już umie",
  "review-states": "Porządek w requestach",
  "strona-kariery": "Strona kariery do uzupełnienia",
  ogloszenia: "Ogłoszenia do nadrobienia",
  "umowy-przedwstepne": "Umowy przedwstępne",
  daily: "Daily",
  seeking: "Dostępni kontraktorzy",
  "seeking-contractors": "Dostępni kontraktorzy",
  trainee: "Telefony na dziś",
  "trainee-rules": "Lista telefonów praktykantów",
  trainees: "Praktykanci",
};

/** Segmenty bez własnej strony — okruszek jest tekstem, nie linkiem do 404. */
const LINKLESS_SEGMENTS = new Set(["sourcing", "prep"]);

const ENTITY_NAME_FETCHERS: Record<string, (id: string) => Promise<string>> = {
  candidates: async (id) => {
    const r = await api.get(`/api/candidates/${id}`);
    return `${r.data.name ?? ""} ${r.data.lastname ?? ""}`.trim() || id;
  },
  // Okruszek czyta rekrutację z zapytania strony (`DynamicLabel`); wpis
  // zostaje, bo mapa mówi też, które segmenty mają nazwę zamiast numeru.
  jobs: async (id) => jobLabel((await api.get(`/api/jobs/${id}`)).data, id),
  clients: async (id) => {
    const r = await api.get(`/api/clients/${id}`);
    return r.data.name ?? id;
  },
  // Sprzedaż: /sales/companies/[id] i /sales/opportunities/[id].
  companies: async (id) => {
    const r = await api.get(`/api/sales/companies/${id}`);
    return r.data.name ?? id;
  },
  opportunities: async (id) => {
    const r = await api.get(`/api/sales/opportunities/${id}`);
    return r.data.title ?? id;
  },
};

interface JobNameFields {
  working_title?: string | null;
  title?: string | null;
  client_reference?: string | null;
}

function jobLabel(job: JobNameFields | undefined, id: string): string {
  const name = job?.working_title || job?.title || id;
  // Numer u klienta przed nazwą, jak na liście i w nagłówku (15.10.2026).
  const [reference] = clientReferenceParts(job?.client_reference);
  return reference ? `${reference} · ${name}` : name;
}

function isNumeric(s: string) {
  return /^\d+$/.test(s);
}

function DynamicLabel({ entityType, id }: { entityType: string; id: string }) {
  // The candidate detail page already fetches the full candidate under
  // ["candidate", <number id>]. Reuse that exact query key here so the
  // breadcrumb name is served from the page's fetch (React Query dedupes by
  // key) instead of issuing a second, heavy request for the same candidate.
  // Other entity types keep their lightweight name-only fetchers.
  // Rekrutacja tak samo: strona `/jobs/[id]` czyta ją pod `["job", <id
  // z adresu>]` (27.10.2026 — wcześniej okruszek pobierał ją drugi raz).
  const isCandidate = entityType === "candidates";
  const isJob = entityType === "jobs";
  const fetcher = ENTITY_NAME_FETCHERS[entityType];
  const { data, isLoading } = useQuery<any>({
    queryKey: isCandidate
      ? ["candidate", Number(id)]
      : isJob
        ? ["job", id]
        : ["breadcrumb-v2", entityType, id],
    queryFn: isCandidate
      ? () => api.get(`/api/candidates/${id}`).then((r) => r.data)
      : isJob
        ? () => api.get(`/api/jobs/${id}`).then((r) => r.data)
        : () => fetcher(id),
    enabled: isCandidate || !!fetcher,
    staleTime: 60_000,
  });
  if (!isCandidate && !fetcher) return <span>{id}</span>;
  if (isLoading) return <span className="opacity-50">…</span>;
  const label = isCandidate
    ? `${data?.name ?? ""} ${data?.lastname ?? ""}`.trim() || id
    : isJob
      ? jobLabel(data, id)
      : (data ?? id);
  return <span>{label}</span>;
}

export function BreadcrumbV2({ className }: { className?: string }) {
  const pathname = usePathname();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  // Next prerenders a 404 at /_not-found, while the browser has the requested
  // URL. Keep the first render stable, then show the actual navigation path.
  const segments = mounted ? pathname.split("/").filter(Boolean) : [];

  if (segments.length === 0) {
    return (
      <span className={cn("text-sm font-medium text-foreground", className)}>
        Dashboard
      </span>
    );
  }

  const crumbs: BreadcrumbCrumb[] = [{ label: "Dashboard", href: "/" }];

  let path = "";
  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i];
    path += "/" + seg;
    const prevSeg = segments[i - 1];
    if (isNumeric(seg) && prevSeg && ENTITY_NAME_FETCHERS[prevSeg]) {
      crumbs.push({
        label: <DynamicLabel entityType={prevSeg} id={seg} />,
        href: path,
        dynamic: true,
      });
    } else if (!isNumeric(seg)) {
      const label =
        SEGMENT_LABELS[seg] ?? (seg.length > 14 ? seg.slice(0, 12) + "…" : seg);
      // „/dashboard" pod „Dashboard" nie powtarza tej samej nazwy dwa razy.
      if (i === 0 && seg === "dashboard") continue;
      crumbs.push({ label, href: path, linkless: LINKLESS_SEGMENTS.has(seg) });
    }
  }

  return <BreadcrumbTrail crumbs={crumbs} className={className} />;
}

export interface BreadcrumbCrumb {
  label: React.ReactNode;
  href: string;
  /** Nazwa encji z API — jedyny okruszek, który wolno skracać w środku ścieżki. */
  dynamic?: boolean;
  linkless?: boolean;
}

/**
 * Sam rysunek ścieżki — osobno, bo harness `/preview/kpi-topbar` stawia go
 * w replice paska bez adresu i bez zapytań.
 *
 * Gdy w pasku brakuje miejsca, ścieżka gubi CAŁE okruszki od początku
 * („Dashboard”, potem kolejne sekcje), a nazwa osoby czy rekrutacji zostaje
 * do końca. 28.10.2026 przy 1280 px rekruter z P0, Ligą i licznikiem celów
 * miał na okruszki 93 px, a „Dashboard › Kandydaci” (178 px, stałe nazwy się
 * nie kurczą) wychodziło pod wyszukiwarkę, nazwa kandydata miała 0 px.
 * Mechanizm jak w liczniku celów: okruszki się zawijają, a ścieżka ma
 * wysokość jednego wiersza, więc nadmiar spada do ukrytego wiersza.
 * `flex-row-reverse` z odwróconym `order` wypełnia wiersz od nazwy na końcu,
 * a DOM (i czytnik ekranu) zostaje w kolejności Dashboard → … → nazwa.
 */
export function BreadcrumbTrail({
  crumbs,
  className,
}: {
  crumbs: BreadcrumbCrumb[];
  className?: string;
}) {
  return (
    <nav
      aria-label="Ścieżka"
      className={cn(
        "flex flex-row-reverse flex-wrap justify-end content-start h-5 overflow-hidden gap-x-1 text-sm min-w-0",
        className,
      )}
    >
      {crumbs.map((c, i) => {
        const isLast = i === crumbs.length - 1;
        return (
          // Stałe nazwy sekcji w środku ścieżki się nie kurczą (UAT M03-B09:
          // „Dash… › Rekr… ›"); skraca się ostatni okruszek i nazwy encji.
          // Nazwa ma sufit 11rem: dłuższa (pełna nazwa rekrutacji) wypchnęłaby
          // sekcje do ukrytego wiersza także przy szerokim oknie. Przy 360 px
          // okruszków to tyle, ile nazwa miała przed 28.10 obok dwóch sekcji.
          <div
            key={c.href}
            data-crumb
            style={{ order: crumbs.length - i }}
            className={cn(
              "flex h-5 items-center gap-1",
              isLast || c.dynamic ? "min-w-0 max-w-44" : "shrink-0",
            )}
          >
            {isLast ? (
              <span className="font-medium text-foreground truncate">
                {c.label}
              </span>
            ) : c.linkless ? (
              <span className="text-muted-foreground truncate">{c.label}</span>
            ) : (
              <Link
                href={c.href}
                className="text-muted-foreground hover:text-foreground truncate transition-colors"
              >
                {c.label}
              </Link>
            )}
            {!isLast && (
              <ChevronRight className="h-3 w-3 text-muted-foreground shrink-0" />
            )}
          </div>
        );
      })}
    </nav>
  );
}
