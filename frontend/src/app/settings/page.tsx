"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import api from "@/lib/api";
import {
  Plug,
  Mail,
  RefreshCw,
  AlertCircle,
  Loader2,
  HelpCircle,
  Sparkles,
  Sliders,
  Coins,
  FileSignature,
  Workflow,
  Stethoscope,
  ChevronRight,
  FileText,
  Users as UsersIcon,
  BarChart3,
  Network,
  MessageSquare,
  Briefcase,
  Cpu,
  Search,
  UserRound,
} from "lucide-react";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { SettingsBreadcrumb } from "@/components/settings/SettingsBreadcrumb";
import Microsoft365Card from "@/components/settings/Microsoft365Card";
import { TeamsPrepStatusCard } from "@/components/settings/TeamsPrepStatusCard";
import { NotificationPreferencesPanel } from "@/components/settings/NotificationPreferencesPanel";
import TeamsNotificationsCard from "@/components/settings/TeamsNotificationsCard";
import { TraffitSyncCard } from "@/components/settings/TraffitSyncCard";
import JobBoardsCard from "@/components/settings/JobBoardsCard";
import EmailTemplatesCard from "@/components/settings/EmailTemplatesCard";
import NotificationDeliverySettings from "@/components/settings/NotificationDeliverySettings";
import { useAuthStore, hasRole, type UserRole } from "@/store/auth";
import { resetScreenSeen } from "@/lib/jarvis/bubble-budget";
import { openJarvis } from "@/lib/jarvis/events";
import {
  findSettingsArea,
  isFinanceReadOnly,
  listedSettingsAreas,
  listedSettingsItems,
  resolveSettingsView,
  searchSettingsItems,
  settingsItemHref,
  type SettingsArea,
  type SettingsAreaId,
  type SettingsItem,
} from "@/lib/settings-registry";
import {
  hasSectionAccess,
  type ProductSection,
  type SectionAccess,
} from "@/lib/section-access";

// Lazy-load heavy tabs — content loaded only when tab activated.
// AdminUsersTab pulls ~30kB+ chunk (user mgmt + modals + import).
// PipelineTemplatesTab pulls @hello-pangea/dnd (~50kB).
const AdminUsersTab = dynamic(
  () => import("@/components/settings/admin/AdminUsersTab"),
  {
    ssr: false,
    loading: () => (
      <div className="p-8 flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-primary" />
      </div>
    ),
  }
);

const EventHistoryTab = dynamic(
  () => import("@/components/settings/EventHistoryTab"),
  {
    ssr: false,
    loading: () => <div className="h-64 animate-pulse bg-muted rounded-xl" />,
  }
);
const SkillDictionaryTab = dynamic(
  () => import("@/components/settings/SkillDictionaryTab"),
  {
    ssr: false,
    loading: () => <div className="h-64 animate-pulse bg-muted rounded-xl" />,
  }
);
const PlacementExclusionsTab = dynamic(
  () => import("@/components/settings/PlacementExclusionsTab"),
  {
    ssr: false,
    loading: () => <div className="h-64 animate-pulse bg-muted rounded-xl" />,
  }
);

const ConflictsRegistryTab = dynamic(
  () => import("@/components/settings/ConflictsRegistryTab"),
  {
    ssr: false,
    loading: () => <div className="h-64 animate-pulse bg-muted rounded-xl" />,
  }
);

const PipelineTemplatesTab = dynamic(
  () => import("@/components/settings/PipelineTemplatesTab"),
  {
    ssr: false,
    loading: () => <div className="h-64 animate-pulse bg-muted rounded-xl" />,
  }
);

// Sub-pages dostępne via direct URL — sklejone razem dla discoverability.
const ADVANCED_LINKS: Array<{
  href: string;
  title: string;
  description: string;
  icon: React.ReactNode;
  roles?: UserRole[];
  section?: ProductSection;
  required?: Exclude<SectionAccess, "none">;
}> = [
  {
    href: "/settings/pipeline-templates",
    title: "Procesy rekrutacyjne",
    description: "Pipeline templates: definicje stagey i przepływów per rekrutację.",
    icon: <Workflow className="w-5 h-5" />,
    roles: ["admin", "delivery_lead"],
    section: "pipeline",
    required: "write",
  },
  {
    href: "/settings/scoring",
    title: "Profile wag scoringu",
    description: "Tunowanie semantic / skills / salary / location / availability per klient.",
    icon: <Sliders className="w-5 h-5" />,
    roles: ["admin", "delivery_lead"],
    section: "insights",
    required: "read",
  },
  {
    href: "/settings/rate-benchmarks",
    title: "Stawki rynkowe",
    description: "Import i zarządzanie benchmarkami stawek (No Fluff Jobs, Bulldogjob, własne).",
    icon: <Coins className="w-5 h-5" />,
    // Globalne benchmarki stawek należą do Finansów, nie do klientowego
    // wyjątku Delivery Leada.
    roles: ["admin", "finance"],
    section: "finance",
  },
  // „Reguły CV per klient" ma teraz WŁASNĄ zakładkę w nagłówku Ustawień
  // (patrz `canManageCvRules`), więc nie dublujemy jej w siatce „Zaawansowane".
  {
    href: "/settings/contract-templates",
    title: "Szablony umów",
    description: "Edytor szablonów kontraktów (B2B, body leasing, fixed-price).",
    icon: <FileSignature className="w-5 h-5" />,
    roles: ["admin", "finance"],
    section: "finance",
  },
  {
    href: "/settings/templates",
    title: "Szablony email",
    description: "Wiadomości szablonowe — outreach, follow-up, rejection.",
    icon: <Mail className="w-5 h-5" />,
  },
  {
    href: "/settings/ai",
    title: "Funkcje AI",
    description: "Globalny wyłącznik + miesięczne limity dla scoringu, generatora ogłoszeń, parsera CV i podsumowań.",
    icon: <Sparkles className="w-5 h-5" />,
    roles: ["admin"],
    section: "system_admin",
  },
  {
    href: "/settings/api-integration",
    title: "Integracja z API",
    description: "Klucze OAuth2 dla zewnętrznych systemów (n8n, ChatGPT, Zapier, ...) z fine-grained scopes.",
    icon: <Plug className="w-5 h-5" />,
    roles: ["admin"],
    section: "system_admin",
  },
  {
    href: "/settings/dictionaries",
    title: "Słowniki",
    description: "Edytowalne taksonomie — branże, powody odrzucenia. Dodaj wartości bez deploya.",
    icon: <FileText className="w-5 h-5" />,
    roles: ["admin"],
    section: "system_admin",
  },
  {
    href: "/settings/entity-fields",
    title: "Konfiguracja pól",
    description: "Dodaj własne pola na profilu kandydata / rekrutacji. Drag-drop layout.",
    icon: <Sliders className="w-5 h-5" />,
    roles: ["admin"],
    section: "system_admin",
  },
  {
    href: "/settings/diagnostics",
    title: "Diagnostyka",
    description: "Stan Voyage AI i Qdrant — połączenia i kolekcje embeddingów.",
    icon: <Stethoscope className="w-5 h-5" />,
    roles: ["admin"],
    section: "system_admin",
  },
  {
    href: "/settings/team-structure",
    title: "Kompetencje i odpowiedzialności",
    description: "Kompetencje Sourcerów, TAC-ów i Rekruterów oraz przypisania Delivery Leadów do klientów.",
    icon: <Network className="w-5 h-5" />,
    roles: ["admin", "head_of_recruitment", "finance"],
  },
  {
    href: "/settings/chats",
    title: "Globalny audyt czatów",
    description: "Przegląd wszystkich rozmów (projekty + kandydaci) z możliwością przeszukania treści.",
    icon: <MessageSquare className="w-5 h-5" />,
    roles: ["admin", "finance"],
  },
  {
    href: "/settings/clients-overview",
    title: "Przegląd klientów",
    description: "Ranking klientów + leaderboard delivery leadów.",
    icon: <BarChart3 className="w-5 h-5" />,
    roles: ["admin", "finance"],
    section: "finance",
  },
  {
    href: "/settings/client-portfolio-preview",
    title: "Podgląd importu klientów",
    description:
      "Read-only plan Excela: dopasowania, KIR, blockery i podejrzenia duplikatów przed apply-once.",
    icon: <FileText className="w-5 h-5" />,
    roles: ["admin", "finance"],
    section: "finance",
  },
  {
    href: "/settings/hiring-managers",
    title: "Top hiring managers",
    description: "KPI hiring managerów w klientach (Phase 9b).",
    icon: <UsersIcon className="w-5 h-5" />,
    roles: ["admin", "head_of_recruitment", "finance"],
    section: "insights",
  },
];

// Finance gets operational read surfaces only. Integration sync, templates,
// scoring, AI, diagnostics and configuration editors remain unavailable.
const FINANCE_READ_ONLY_LINKS = new Set([
  "/settings/rate-benchmarks",
  "/settings/contract-templates",
  "/settings/team-structure",
  "/settings/chats",
  "/settings/clients-overview",
  "/settings/client-portfolio-preview",
  "/settings/hiring-managers",
]);

// ── Settings page ─────────────────────────────────────────────────────────────
//
// Jedno wejście (22.09.2026, propozycja „kafelki"): strona startowa z obszarami,
// obszar = krótka lista pozycji, pozycja = sam ekran. Widok wynika WYŁĄCZNIE
// z adresu (`?area=`, `?item=`; stare `?tab=` przez `LEGACY_SETTINGS_TABS`),
// więc F5, „Wstecz" i miękka nawigacja zawsze pokazują to samo. Mapa pozycji
// i reguły widoczności: `lib/settings-registry.ts`.

const AREA_ICONS: Record<SettingsAreaId, React.ComponentType<{ className?: string }>> = {
  me: UserRound,
  team: UsersIcon,
  rec: Briefcase,
  deals: FileSignature,
  sys: Cpu,
};

function SettingsItemRows({ items, showArea = false }: { items: SettingsItem[]; showArea?: boolean }) {
  return (
    <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">
      {items.map((item) => (
        <li key={item.id}>
          <Link
            href={settingsItemHref(item)}
            className="flex min-h-14 items-center gap-4 px-5 py-3.5 transition-colors hover:bg-muted/60"
          >
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="text-[15px] font-semibold text-foreground">{item.title}</span>
              <span className="text-sm text-muted-foreground">{item.description}</span>
            </span>
            {showArea && (
              <span className="shrink-0 text-xs text-muted-foreground">
                {findSettingsArea(item.area)?.name}
              </span>
            )}
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          </Link>
        </li>
      ))}
    </ul>
  );
}

function SettingsHome({ areas, user }: { areas: SettingsArea[]; user: Parameters<typeof searchSettingsItems>[0] }) {
  const [query, setQuery] = useState("");
  const results = searchSettingsItems(user, query);
  const searching = query.trim() !== "";
  return (
    <>
      <div>
        <h1 className="text-2xl font-bold text-foreground">Ustawienia</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">Wybierz obszar albo wpisz, czego szukasz.</p>
      </div>
      <label className="relative block">
        <span className="sr-only">Szukaj w ustawieniach</span>
        <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Np. rola, reguły CV, Traffit"
          className="h-12 w-full rounded-xl border border-border bg-card pl-11 pr-4 text-base md:text-[15px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
        />
      </label>
      {!searching && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {areas.map((area) => {
            const Icon = AREA_ICONS[area.id];
            return (
              <Link
                key={area.id}
                href={`/settings?area=${area.id}`}
                className="flex min-h-36 flex-col gap-2.5 rounded-2xl border border-border bg-card p-5 transition-all hover:border-primary hover:shadow-xs"
              >
                <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <Icon className="h-5 w-5" />
                </span>
                <span className="text-base font-semibold text-foreground">{area.name}</span>
                <span className="text-sm text-muted-foreground">{area.hint}</span>
              </Link>
            );
          })}
        </div>
      )}
      {searching && results.length > 0 && <SettingsItemRows items={results} showArea />}
      {searching && results.length === 0 && (
        <p className="text-sm text-muted-foreground">Nic nie pasuje do „{query.trim()}”.</p>
      )}
    </>
  );
}

function SettingsItemBody({ item, user }: { item: SettingsItem; user: Parameters<typeof hasSectionAccess>[0] }) {
  switch (item.id) {
    case "notifications":
      return <NotificationDeliverySettings />;
    case "outlook":
      return <Microsoft365Card />;
    case "my-notifications":
      return <NotificationPreferencesPanel />;
    case "people":
      return <AdminUsersTab embedded />;
    case "stages":
      return <PipelineTemplatesTab />;
    case "mail":
      return (
        <div className="space-y-4">
          <EmailTemplatesCard />
          <div className="rounded-2xl border border-border bg-card p-5 text-sm text-muted-foreground">
            Szablony odrzuceń mają własny edytor:{" "}
            <Link href="/settings/templates" className="font-medium text-primary hover:underline">
              otwórz szablony odrzuceń
            </Link>
          </div>
        </div>
      );
    case "skills":
      return <SkillDictionaryTab />;
    case "traffit":
      return <TraffitSyncCard />;
    case "job-boards":
      return <JobBoardsCard />;
    case "teams-prep":
      return <TeamsPrepStatusCard />;
    case "history":
      return <EventHistoryTab />;
    case "placements":
      return <PlacementExclusionsTab />;
    case "teams":
      return <TeamsNotificationsCard />;
    case "coaching":
      return <CoachingSettings />;
    case "conflicts":
      return <ConflictsRegistryTab />;
    case "help":
      return <OnboardingSettings />;
    case "advanced":
      return <AdvancedLinksGrid user={user} />;
    default:
      return null;
  }
}

function AdvancedLinksGrid({ user }: { user: Parameters<typeof hasSectionAccess>[0] }) {
  const financeReadOnly = isFinanceReadOnly(user as Parameters<typeof isFinanceReadOnly>[0]);
  const links = ADVANCED_LINKS.filter(
    (link) =>
      (!financeReadOnly || FINANCE_READ_ONLY_LINKS.has(link.href)) &&
      (!link.roles || hasRole(user as Parameters<typeof hasRole>[0], ...link.roles)) &&
      (!link.section || hasSectionAccess(user, link.section, link.required ?? "read")),
  );
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {links.map((link) => (
        <Link
          key={link.href}
          href={link.href}
          className="group rounded-2xl border border-border bg-card p-5 transition-all hover:border-primary hover:shadow-xs"
        >
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
              {link.icon}
            </div>
            <div className="min-w-0 flex-1">
              <h3 className="text-sm font-semibold text-foreground">{link.title}</h3>
              <p className="mt-1 text-xs text-muted-foreground">{link.description}</p>
            </div>
          </div>
        </Link>
      ))}
    </div>
  );
}

export default function SettingsPage() {
  const { user, hydrated } = useAuthStore();
  const searchParams = useSearchParams();

  // The auth store hydrates `user` from localStorage in a post-mount effect
  // (AppShellV2). Until then `user` is null and every role-gated area would be
  // filtered out and flash in once hydration completes.
  if (!hydrated) {
    return <div className="p-6 text-muted-foreground">Ładowanie…</div>;
  }

  const view = resolveSettingsView(user, {
    item: searchParams?.get("item"),
    area: searchParams?.get("area"),
    tab: searchParams?.get("tab"),
  });
  const wide = view.kind === "item" && view.item.wide;

  return (
    <div className={cn("mx-auto space-y-6", wide ? "max-w-7xl" : "max-w-4xl")}>
      {view.kind === "home" && (
        <SettingsHome areas={listedSettingsAreas(user)} user={user} />
      )}

      {view.kind === "area" && (
        <>
          <SettingsBreadcrumb area={view.area} />
          <div>
            <h1 className="text-2xl font-bold text-foreground">{view.area.name}</h1>
            <p className="mt-0.5 text-sm text-muted-foreground">{view.area.hint}</p>
          </div>
          <SettingsItemRows
            items={listedSettingsItems(user).filter((i) => i.area === view.area.id)}
          />
        </>
      )}

      {view.kind === "item" && (
        <>
          <SettingsBreadcrumb area={view.area} item={view.item} />
          {!view.item.ownHeader && (
            <div>
              <h1 className="text-2xl font-bold text-foreground">{view.item.title}</h1>
              <p className="mt-0.5 text-sm text-muted-foreground">{view.item.description}</p>
            </div>
          )}
          <SettingsItemBody item={view.item} user={user} />
        </>
      )}
    </div>
  );
}


function CoachingSettings() {
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["user-preferences", "me"],
    queryFn: () =>
      api.get("/api/users/me/preferences").then((r) => r.data as { kpi_coach_enabled: boolean }),
    staleTime: 60 * 1000,
  });

  const { mutate: update, isPending } = useMutation({
    mutationFn: (kpi_coach_enabled: boolean) =>
      api
        .patch("/api/users/me/preferences", { kpi_coach_enabled })
        .then((r) => r.data as { kpi_coach_enabled: boolean }),
    onSuccess: (next) => {
      queryClient.setQueryData(["user-preferences", "me"], next);
    },
  });

  const enabled = data?.kpi_coach_enabled ?? true;

  return (
    <div className="bg-card dark:bg-muted rounded-2xl border border-border dark:border-border p-6">
      <div className="flex items-start gap-4 mb-6">
        <div className="w-12 h-12 rounded-xl bg-emerald-50 dark:bg-emerald-900/30 flex items-center justify-center shrink-0">
          <Sparkles className="w-6 h-6 text-emerald-500" />
        </div>
        <div className="flex-1">
          <h3 className="text-base font-bold text-foreground dark:text-foreground">
            Coaching KPI
          </h3>
          <p className="text-sm text-muted-foreground dark:text-muted-foreground mt-0.5">
            System na bieżąco chwali gdy wyrobisz target i przypomina gdy idzie
            za wolno. Działa w godzinach 09:00–17:30 (pon–pt).
          </p>
        </div>
      </div>

      <div className="flex items-center justify-between gap-4 p-4 border border-border dark:border-border rounded-xl">
        <div>
          <p className="text-sm font-semibold text-foreground dark:text-muted-foreground">
            Włącz coaching
          </p>
          <p className="text-xs text-muted-foreground dark:text-muted-foreground mt-0.5">
            Toast + powiadomienie w dzwonku. Bez spamu — dedup per KPI / okres,
            max 3 przypomnienia dziennie per wskaźnik.
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          disabled={isLoading || isPending}
          onClick={() => update(!enabled)}
          className={cn(
            "relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full transition-colors",
            "focus:outline-hidden focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2",
            enabled
              ? "bg-emerald-500"
              : "bg-muted dark:bg-gray-600",
            (isLoading || isPending) && "opacity-60 cursor-wait",
          )}
        >
          <span
            className={cn(
              "pointer-events-none inline-block h-5 w-5 transform rounded-full bg-card shadow-sm ring-0 transition-transform mt-0.5",
              enabled ? "translate-x-5" : "translate-x-0.5",
            )}
          />
        </button>
      </div>

      {!isLoading && !enabled && (
        <div className="flex items-start gap-2 text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 mt-4">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>
            Coaching wyłączony — nie będziesz dostawać toastów ani powiadomień z
            KPI Coach. Sam widget KPI w dashboardzie pozostaje widoczny.
          </span>
        </div>
      )}
    </div>
  );
}

function OnboardingSettings() {
  // Dawny czterokrokowy przewodnik (zgnił: „Ogłoszenia”) zastąpiły
  // przewodniki ekranów Jarvisa — dymek raz na ekran i przycisk „?” w panelu.
  const userId = useAuthStore((s) => s.user?.id);
  const handleReset = () => {
    resetScreenSeen(userId);
    openJarvis({});
  };

  return (
    <div className="bg-card dark:bg-muted rounded-2xl border border-border dark:border-border p-6">
      <div className="flex items-start gap-4 mb-6">
        <div className="w-12 h-12 rounded-xl bg-primary/10 dark:bg-primary/30 flex items-center justify-center shrink-0">
          <HelpCircle className="w-6 h-6 text-primary" />
        </div>
        <div>
          <h3 className="text-base font-bold text-foreground dark:text-foreground">Wskazówki na ekranach</h3>
          <p className="text-sm text-muted-foreground dark:text-muted-foreground mt-0.5">
            Asystent przy pierwszej wizycie na ekranie podpowiada, co się tu robi. Na każdym ekranie
            możesz też kliknąć „?” w jego panelu.
          </p>
        </div>
      </div>

      <button
        type="button"
        onClick={handleReset}
        className="flex items-center gap-2 px-4 py-2.5 bg-primary text-white rounded-xl text-sm font-medium hover:bg-primary/90 transition-colors"
      >
        <RefreshCw className="w-4 h-4" />
        Pokaż wskazówki od nowa
      </button>

      <div className="mt-6 pt-6 border-t border-border dark:border-border">
        <h4 className="text-sm font-semibold text-foreground dark:text-muted-foreground mb-3">Skróty klawiszowe</h4>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs text-muted-foreground dark:text-muted-foreground">
          <div className="flex justify-between p-2 bg-muted dark:bg-muted rounded-lg">
            <span>Wyszukiwanie</span>
            <kbd className="font-mono bg-card dark:bg-gray-600 px-1.5 py-0.5 rounded border border-border dark:border-gray-500">⌘K</kbd>
          </div>
          <div className="flex justify-between p-2 bg-muted dark:bg-muted rounded-lg">
            <span>Dodaj kandydata</span>
            <kbd className="font-mono bg-card dark:bg-gray-600 px-1.5 py-0.5 rounded border border-border dark:border-gray-500">⌘⇧C</kbd>
          </div>
          <div className="flex justify-between p-2 bg-muted dark:bg-muted rounded-lg">
            <span>Dodaj rekrutację</span>
            <kbd className="font-mono bg-card dark:bg-gray-600 px-1.5 py-0.5 rounded border border-border dark:border-gray-500">⌘⇧J</kbd>
          </div>
          <div className="flex justify-between p-2 bg-muted dark:bg-muted rounded-lg">
            <span>Skróty</span>
            <kbd className="font-mono bg-card dark:bg-gray-600 px-1.5 py-0.5 rounded border border-border dark:border-gray-500">?</kbd>
          </div>
        </div>
      </div>
    </div>
  );
}
