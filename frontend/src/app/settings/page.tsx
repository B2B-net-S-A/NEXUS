"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import api from "@/lib/api";
import {
  Settings,
  Plug,
  Mail,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  Loader2,
  ExternalLink,
  Mic,
  Clock,
  HelpCircle,
  Sparkles,
  Sliders,
  Coins,
  FileSignature,
  Workflow,
  Stethoscope,
  ChevronRight,
  FileText,
  Shield,
  Users as UsersIcon,
  BarChart3,
  Network,
  MessageSquare,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { formatRelativeTime } from "@/lib/utils";
import Link from "next/link";
import Microsoft365Card from "@/components/settings/Microsoft365Card";
import TeamsNotificationsCard from "@/components/settings/TeamsNotificationsCard";
import { TraffitSyncCard } from "@/components/settings/TraffitSyncCard";
import EmailTemplatesCard from "@/components/settings/EmailTemplatesCard";
import { useAuthStore, hasRole, type UserRole } from "@/store/auth";
import { clearOnboardingCompleted } from "@/lib/onboarding-storage";

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

const PipelineTemplatesTab = dynamic(
  () => import("@/components/settings/PipelineTemplatesTab"),
  {
    ssr: false,
    loading: () => <div className="h-64 animate-pulse bg-muted rounded-xl" />,
  }
);

// ── Tab config ────────────────────────────────────────────────────────────────

type Tab =
  | "integracje"
  | "szablony"
  | "coaching"
  | "procesy"
  | "administracja"
  | "zaawansowane"
  | "pomoc";

interface TabConfig {
  id: Tab;
  label: string;
  icon: React.ReactNode;
  /** Jeśli ustawione — tab widoczny tylko dla użytkowników z którąkolwiek z tych ról. */
  roles?: UserRole[];
}

const TABS: TabConfig[] = [
  { id: "integracje", label: "Integracje", icon: <Plug className="w-4 h-4" /> },
  { id: "szablony", label: "Szablony email", icon: <Mail className="w-4 h-4" /> },
  { id: "coaching", label: "Coaching KPI", icon: <Sparkles className="w-4 h-4" /> },
  {
    id: "procesy",
    label: "Procesy",
    icon: <Workflow className="w-4 h-4" />,
    roles: ["admin", "delivery_lead"],
  },
  {
    id: "administracja",
    label: "Administracja",
    icon: <Shield className="w-4 h-4" />,
    roles: ["admin"],
  },
  { id: "zaawansowane", label: "Zaawansowane", icon: <Settings className="w-4 h-4" /> },
  { id: "pomoc", label: "Pomoc", icon: <HelpCircle className="w-4 h-4" /> },
];

// Taby które wymagają szerszego kontenera (tabele, dnd, grid).
const WIDE_TABS: Tab[] = ["procesy", "administracja"];

// Sub-pages dostępne via direct URL — sklejone razem dla discoverability.
const ADVANCED_LINKS: Array<{
  href: string;
  title: string;
  description: string;
  icon: React.ReactNode;
  roles?: UserRole[];
}> = [
  {
    href: "/settings/pipeline-templates",
    title: "Procesy rekrutacyjne",
    description: "Pipeline templates: definicje stagey i przepływów per ofertę.",
    icon: <Workflow className="w-5 h-5" />,
    roles: ["admin", "delivery_lead"],
  },
  {
    href: "/settings/scoring",
    title: "Profile wag scoringu",
    description: "Tunowanie semantic / skills / salary / location / availability per klient.",
    icon: <Sliders className="w-5 h-5" />,
  },
  {
    href: "/settings/rate-benchmarks",
    title: "Stawki rynkowe",
    description: "Import i zarządzanie benchmarkami stawek (No Fluff Jobs, Bulldogjob, własne).",
    icon: <Coins className="w-5 h-5" />,
    // R0 (plan analytics 2026-07-16): benchmarki stawek = finanse (DL+/admin).
    roles: ["admin", "delivery_lead"],
  },
  {
    href: "/settings/contract-templates",
    title: "Szablony umów",
    description: "Edytor szablonów kontraktów (B2B, body leasing, fixed-price).",
    icon: <FileSignature className="w-5 h-5" />,
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
  },
  {
    href: "/settings/api-integration",
    title: "Integracja z API",
    description: "Klucze OAuth2 dla zewnętrznych systemów (n8n, ChatGPT, Zapier, ...) z fine-grained scopes.",
    icon: <Plug className="w-5 h-5" />,
  },
  {
    href: "/settings/dictionaries",
    title: "Słowniki",
    description: "Edytowalne taksonomie — branże, powody odrzucenia. Dodaj wartości bez deploya.",
    icon: <FileText className="w-5 h-5" />,
  },
  {
    href: "/settings/entity-fields",
    title: "Konfiguracja pól",
    description: "Dodaj własne pola na profilu kandydata / rekrutacji. Drag-drop layout.",
    icon: <Sliders className="w-5 h-5" />,
  },
  {
    href: "/settings/diagnostics",
    title: "Diagnostyka",
    description: "Status komponentów, kolejki, background tasks.",
    icon: <Stethoscope className="w-5 h-5" />,
  },
  {
    href: "/settings/team-structure",
    title: "Macierze przypisań",
    description: "TAC × kategorie kompetencji, TAC → DL, DL → klienci, LinkedIn farming.",
    icon: <Network className="w-5 h-5" />,
    roles: ["admin"],
  },
  {
    href: "/settings/linkedin-metrics",
    title: "Aktywność LinkedIn",
    description: "Bulk edit dziennych liczb (CV / Msg / Resp) per TAC/sourcer.",
    icon: <BarChart3 className="w-5 h-5" />,
    roles: ["admin"],
  },
  {
    href: "/settings/chats",
    title: "Globalny audyt czatów",
    description: "Przegląd wszystkich rozmów (projekty + kandydaci) z możliwością przeszukania treści.",
    icon: <MessageSquare className="w-5 h-5" />,
    roles: ["admin"],
  },
  {
    href: "/settings/clients-overview",
    title: "Przegląd klientów",
    description: "Ranking klientów + leaderboard delivery leadów.",
    icon: <BarChart3 className="w-5 h-5" />,
    roles: ["admin", "head_of_recruitment"],
  },
  {
    href: "/settings/hiring-managers",
    title: "Top hiring managers",
    description: "KPI hiring managerów w klientach (Phase 9b).",
    icon: <UsersIcon className="w-5 h-5" />,
    roles: ["admin", "head_of_recruitment"],
  },
];

// ── Fireflies Card ────────────────────────────────────────────────────────────

function FirefliesCard() {
  const [syncResult, setSyncResult] = useState<{ synced: number; linked: number; errors: number; error?: string } | null>(null);

  const { data: status, isLoading, refetch } = useQuery({
    queryKey: ["fireflies-status"],
    queryFn: () => api.get("/api/fireflies/status").then((r) => r.data),
    staleTime: 30 * 1000,
  });

  const { mutate: sync, isPending: syncing } = useMutation({
    mutationFn: () => api.get("/api/fireflies/sync").then((r) => r.data),
    onSuccess: (data) => {
      setSyncResult(data);
      refetch();
    },
  });

  const { data: transcripts } = useQuery({
    queryKey: ["fireflies-transcripts"],
    queryFn: () => api.get("/api/fireflies/transcripts?limit=5").then((r) => r.data),
    staleTime: 60 * 1000,
  });

  const isConnected = status?.connected && !status?.error;

  return (
    <div className="bg-card dark:bg-muted rounded-2xl border border-border dark:border-border p-6">
      <div className="flex items-start gap-4 mb-6">
        <div className="w-12 h-12 rounded-xl bg-orange-50 flex items-center justify-center shrink-0">
          <Mic className="w-6 h-6 text-orange-500" />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-bold text-foreground dark:text-foreground">Fireflies.ai</h3>
            <span
              className={cn(
                "text-xs px-2 py-0.5 rounded-full font-medium",
                isLoading ? "bg-muted text-muted-foreground" :
                isConnected ? "bg-green-100 text-green-700" :
                "bg-destructive/15 text-destructive"
              )}
            >
              {isLoading ? "Sprawdzanie..." : isConnected ? "Połączony" : "Błąd połączenia"}
            </span>
          </div>
          <p className="text-sm text-muted-foreground dark:text-muted-foreground mt-0.5">
            Automatyczna synchronizacja transkrypcji rozmów z kandydatami
          </p>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4 mb-5">
        <div className="bg-muted dark:bg-muted rounded-xl p-3 text-center">
          <p className="text-xl font-bold text-foreground dark:text-foreground">
            {status?.transcript_count ?? "—"}
          </p>
          <p className="text-xs text-muted-foreground dark:text-muted-foreground mt-0.5">Transkrypcji w bazie</p>
        </div>
        <div className="bg-muted dark:bg-muted rounded-xl p-3 text-center col-span-2">
          <div className="flex items-center justify-center gap-1.5">
            <Clock className="w-3.5 h-3.5 text-muted-foreground" />
            <p className="text-sm font-medium text-foreground dark:text-muted-foreground">
              {status?.last_synced_at
                ? formatRelativeTime(status.last_synced_at)
                : "Jeszcze nie synchronizowano"}
            </p>
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">Ostatnia synchronizacja</p>
        </div>
      </div>

      {status?.error && (
        <div className="flex items-start gap-2 text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-xl px-4 py-3 mb-4">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{status.error}</span>
        </div>
      )}

      {syncResult && (
        <div className="bg-primary/10 dark:bg-primary/10 border border-primary/20 dark:border-primary/30 rounded-xl p-4 mb-4 text-sm">
          <p className="font-semibold text-primary dark:text-primary mb-2">Wynik synchronizacji:</p>
          <div className="flex gap-4 text-xs">
            <span className="text-green-700">✓ {syncResult.synced} zsynchronizowanych</span>
            <span className="text-primary">🔗 {syncResult.linked} powiązanych z kandydatami</span>
            {syncResult.errors > 0 && (
              <span className="text-destructive">✕ {syncResult.errors} błędów</span>
            )}
          </div>
          {syncResult.error && (
            <p className="text-destructive mt-1">{syncResult.error}</p>
          )}
        </div>
      )}

      {transcripts && transcripts.length > 0 && (
        <div className="mb-5">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
            Ostatnie transkrypcje
          </p>
          <div className="space-y-2">
            {transcripts.slice(0, 4).map((t: { id: string; title: string; candidate_id?: number; created_at?: string }) => (
              <div
                key={t.id}
                className="flex items-center gap-3 text-sm py-2 border-b border-border dark:border-border last:border-0"
              >
                <Mic className="w-3.5 h-3.5 text-orange-400 shrink-0" />
                <span className="flex-1 truncate text-foreground dark:text-muted-foreground">{t.title}</span>
                {t.candidate_id && (
                  <Link
                    href={`/candidates?id=${t.candidate_id}`}
                    className="text-xs text-primary hover:underline shrink-0"
                  >
                    Kandydat →
                  </Link>
                )}
                <span className="text-xs text-muted-foreground shrink-0">
                  {t.created_at ? formatRelativeTime(t.created_at) : ""}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="flex gap-3">
        <button
          onClick={() => sync()}
          disabled={syncing}
          className="flex items-center gap-2 px-4 py-2 bg-orange-500 hover:bg-orange-600 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
        >
          {syncing ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Synchronizuję...
            </>
          ) : (
            <>
              <RefreshCw className="w-4 h-4" />
              Synchronizuj
            </>
          )}
        </button>
        <a
          href="https://fireflies.ai"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 px-4 py-2 border border-border dark:border-border text-muted-foreground dark:text-muted-foreground hover:bg-muted dark:hover:bg-muted rounded-lg text-sm font-medium transition-colors"
        >
          <ExternalLink className="w-4 h-4" />
          Otwórz Fireflies
        </a>
      </div>
    </div>
  );
}

// ── Settings page ─────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const { user, hydrated } = useAuthStore();
  const [activeTab, setActiveTab] = useState<Tab>("integracje");

  // The auth store hydrates `user` from localStorage in a post-mount effect
  // (AppShellV2). Until then `user` is null, so role-gated tabs (Procesy,
  // Administracja) and admin advanced-links get filtered out and flash in once
  // hydration completes. Gate on `hydrated` like the sibling settings pages
  // (linkedin-metrics, team-structure) to avoid the flash-of-missing-tabs.
  if (!hydrated) {
    return <div className="p-6 text-muted-foreground">Ładowanie…</div>;
  }

  const visibleTabs = TABS.filter((tab) => !tab.roles || hasRole(user, ...tab.roles));
  const visibleAdvancedLinks = ADVANCED_LINKS.filter(
    (link) => !link.roles || hasRole(user, ...link.roles)
  );

  const isWide = WIDE_TABS.includes(activeTab);
  const containerClass = isWide ? "max-w-7xl mx-auto space-y-6" : "max-w-4xl mx-auto space-y-6";

  return (
    <div className={containerClass}>
      <div>
        <h1 className="text-2xl font-bold text-foreground dark:text-foreground">Ustawienia</h1>
        <p className="text-sm text-muted-foreground dark:text-muted-foreground mt-0.5">
          Zarządzaj integracjami i konfiguracją systemu
        </p>
      </div>

      <div className="flex gap-1 bg-muted dark:bg-muted p-1 rounded-xl w-fit flex-wrap">
        {visibleTabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all",
              activeTab === tab.id
                ? "bg-card dark:bg-muted text-foreground dark:text-foreground shadow-xs"
                : "text-muted-foreground dark:text-muted-foreground hover:text-foreground dark:hover:text-muted-foreground"
            )}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "integracje" && (
        <div className="space-y-4">
          <Microsoft365Card />
          <FirefliesCard />
          <TeamsNotificationsCard />
          <TraffitSyncCard />

          <div className="bg-muted dark:bg-muted/50 rounded-2xl border border-dashed border-border dark:border-border p-8 text-center">
            <Plug className="w-8 h-8 text-muted-foreground mx-auto mb-2" />
            <p className="text-sm text-muted-foreground">Więcej integracji wkrótce</p>
            <p className="text-xs text-muted-foreground mt-1">LinkedIn, Slack...</p>
          </div>
        </div>
      )}

      {activeTab === "szablony" && (
        <div className="space-y-4">
          <EmailTemplatesCard />
          <div className="bg-card dark:bg-muted rounded-2xl border border-border dark:border-border p-6 text-center">
            <Mail className="w-8 h-8 text-muted-foreground mx-auto mb-2" />
            <p className="text-sm text-muted-foreground dark:text-muted-foreground">
              Szukasz szablonów odrzucenia? Są zarządzane na osobnej stronie.
            </p>
            <Link
              href="/settings/templates"
              className="inline-flex items-center gap-2 mt-3 text-sm text-primary hover:underline font-medium"
            >
              Przejdź do szablonów odrzucenia <ExternalLink className="w-3.5 h-3.5" />
            </Link>
          </div>
        </div>
      )}

      {activeTab === "coaching" && <CoachingSettings />}

      {activeTab === "procesy" && <PipelineTemplatesTab />}

      {activeTab === "administracja" && <AdminUsersTab />}

      {activeTab === "zaawansowane" && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {visibleAdvancedLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="group bg-card dark:bg-muted rounded-2xl border border-border dark:border-border p-5 hover:border-primary hover:shadow-xs transition-all"
            >
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 rounded-xl bg-primary/10 text-primary flex items-center justify-center shrink-0">
                  {link.icon}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="text-sm font-semibold text-foreground dark:text-foreground">
                      {link.title}
                    </h3>
                    <ChevronRight className="w-4 h-4 text-muted-foreground group-hover:text-primary group-hover:translate-x-0.5 transition-all shrink-0" />
                  </div>
                  <p className="text-xs text-muted-foreground dark:text-muted-foreground mt-1">
                    {link.description}
                  </p>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}

      {activeTab === "pomoc" && <OnboardingSettings />}
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
  const [shown, setShown] = useState(false);

  const handleReset = () => {
    clearOnboardingCompleted();
    setShown(true);
    setTimeout(() => {
      window.location.reload();
    }, 1500);
  };

  return (
    <div className="bg-card dark:bg-muted rounded-2xl border border-border dark:border-border p-6">
      <div className="flex items-start gap-4 mb-6">
        <div className="w-12 h-12 rounded-xl bg-primary/10 dark:bg-primary/30 flex items-center justify-center shrink-0">
          <HelpCircle className="w-6 h-6 text-primary" />
        </div>
        <div>
          <h3 className="text-base font-bold text-foreground dark:text-foreground">Przewodnik wprowadzający</h3>
          <p className="text-sm text-muted-foreground dark:text-muted-foreground mt-0.5">
            Pokaż ponownie przewodnik po Nexus
          </p>
        </div>
      </div>

      {shown ? (
        <div className="flex items-center gap-2 text-sm text-green-700 bg-green-50 border border-green-200 rounded-xl px-4 py-3">
          <CheckCircle2 className="w-4 h-4" />
          Przewodnik zostanie wyświetlony po przeładowaniu strony
        </div>
      ) : (
        <button
          onClick={handleReset}
          className="flex items-center gap-2 px-4 py-2.5 bg-primary text-white rounded-xl text-sm font-medium hover:bg-primary/90 transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
          Pokaż przewodnik ponownie
        </button>
      )}

      <div className="mt-6 pt-6 border-t border-border dark:border-border">
        <h4 className="text-sm font-semibold text-foreground dark:text-muted-foreground mb-3">Skróty klawiszowe</h4>
        <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground dark:text-muted-foreground">
          <div className="flex justify-between p-2 bg-muted dark:bg-muted rounded-lg">
            <span>Wyszukiwanie</span>
            <kbd className="font-mono bg-card dark:bg-gray-600 px-1.5 py-0.5 rounded border border-border dark:border-gray-500">⌘K</kbd>
          </div>
          <div className="flex justify-between p-2 bg-muted dark:bg-muted rounded-lg">
            <span>Dodaj kandydata</span>
            <kbd className="font-mono bg-card dark:bg-gray-600 px-1.5 py-0.5 rounded border border-border dark:border-gray-500">⌘⇧C</kbd>
          </div>
          <div className="flex justify-between p-2 bg-muted dark:bg-muted rounded-lg">
            <span>Dodaj ofertę</span>
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
