"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
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
} from "lucide-react";
import { cn } from "@/lib/utils";
import { formatRelativeTime } from "@/lib/utils";
import Link from "next/link";

// ── Tab config ────────────────────────────────────────────────────────────────

type Tab = "integracje" | "szablony" | "onboarding";

const TABS: Array<{ id: Tab; label: string; icon: React.ReactNode }> = [
  { id: "integracje", label: "Integracje", icon: <Plug className="w-4 h-4" /> },
  { id: "szablony", label: "Szablony email", icon: <Mail className="w-4 h-4" /> },
  { id: "onboarding", label: "Pomoc", icon: <HelpCircle className="w-4 h-4" /> },
];

// ── Fireflies Card ────────────────────────────────────────────────────────────

function FirefliesCard() {
  const [syncResult, setSyncResult] = useState<any>(null);

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
    <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-6">
      {/* Header */}
      <div className="flex items-start gap-4 mb-6">
        <div className="w-12 h-12 rounded-xl bg-orange-50 flex items-center justify-center flex-shrink-0">
          <Mic className="w-6 h-6 text-orange-500" />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-bold text-gray-900 dark:text-gray-100">Fireflies.ai</h3>
            <span
              className={cn(
                "text-xs px-2 py-0.5 rounded-full font-medium",
                isLoading ? "bg-gray-100 text-gray-500" :
                isConnected ? "bg-green-100 text-green-700" :
                "bg-red-100 text-red-700"
              )}
            >
              {isLoading ? "Sprawdzanie..." : isConnected ? "Połączony" : "Błąd połączenia"}
            </span>
          </div>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
            Automatyczna synchronizacja transkrypcji rozmów z kandydatami
          </p>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4 mb-5">
        <div className="bg-gray-50 dark:bg-gray-700 rounded-xl p-3 text-center">
          <p className="text-xl font-bold text-gray-900 dark:text-gray-100">
            {status?.transcript_count ?? "—"}
          </p>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">Transkrypcji w bazie</p>
        </div>
        <div className="bg-gray-50 dark:bg-gray-700 rounded-xl p-3 text-center col-span-2">
          <div className="flex items-center justify-center gap-1.5">
            <Clock className="w-3.5 h-3.5 text-gray-400" />
            <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
              {status?.last_synced_at
                ? formatRelativeTime(status.last_synced_at)
                : "Jeszcze nie synchronizowano"}
            </p>
          </div>
          <p className="text-xs text-gray-500 mt-0.5">Ostatnia synchronizacja</p>
        </div>
      </div>

      {/* Error */}
      {status?.error && (
        <div className="flex items-start gap-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl px-4 py-3 mb-4">
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span>{status.error}</span>
        </div>
      )}

      {/* Sync result */}
      {syncResult && (
        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-xl p-4 mb-4 text-sm">
          <p className="font-semibold text-blue-800 dark:text-blue-300 mb-2">Wynik synchronizacji:</p>
          <div className="flex gap-4 text-xs">
            <span className="text-green-700">✓ {syncResult.synced} zsynchronizowanych</span>
            <span className="text-blue-700">🔗 {syncResult.linked} powiązanych z kandydatami</span>
            {syncResult.errors > 0 && (
              <span className="text-red-700">✕ {syncResult.errors} błędów</span>
            )}
          </div>
          {syncResult.error && (
            <p className="text-red-600 mt-1">{syncResult.error}</p>
          )}
        </div>
      )}

      {/* Recent transcripts */}
      {transcripts && transcripts.length > 0 && (
        <div className="mb-5">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
            Ostatnie transkrypcje
          </p>
          <div className="space-y-2">
            {transcripts.slice(0, 4).map((t: any) => (
              <div
                key={t.id}
                className="flex items-center gap-3 text-sm py-2 border-b border-gray-100 dark:border-gray-700 last:border-0"
              >
                <Mic className="w-3.5 h-3.5 text-orange-400 flex-shrink-0" />
                <span className="flex-1 truncate text-gray-700 dark:text-gray-300">{t.title}</span>
                {t.candidate_id && (
                  <Link
                    href={`/candidates?id=${t.candidate_id}`}
                    className="text-xs text-blue-600 hover:underline flex-shrink-0"
                  >
                    Kandydat →
                  </Link>
                )}
                <span className="text-xs text-gray-400 flex-shrink-0">
                  {t.created_at ? formatRelativeTime(t.created_at) : ""}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Action */}
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
          className="flex items-center gap-2 px-4 py-2 border border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 rounded-lg text-sm font-medium transition-colors"
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
  const [activeTab, setActiveTab] = useState<Tab>("integracje");

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Ustawienia</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
          Zarządzaj integracjami i konfiguracją systemu
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-100 dark:bg-gray-800 p-1 rounded-xl w-fit">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all",
              activeTab === tab.id
                ? "bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 shadow-sm"
                : "text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
            )}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === "integracje" && (
        <div className="space-y-4">
          <FirefliesCard />

          {/* Placeholder for future integrations */}
          <div className="bg-gray-50 dark:bg-gray-800/50 rounded-2xl border border-dashed border-gray-200 dark:border-gray-700 p-8 text-center">
            <Plug className="w-8 h-8 text-gray-300 mx-auto mb-2" />
            <p className="text-sm text-gray-400">Więcej integracji wkrótce</p>
            <p className="text-xs text-gray-400 mt-1">LinkedIn, CloudTalk, Slack...</p>
          </div>
        </div>
      )}

      {activeTab === "szablony" && (
        <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-6 text-center">
          <Mail className="w-8 h-8 text-gray-300 mx-auto mb-2" />
          <p className="text-sm text-gray-600 dark:text-gray-400">
            Szablony email zarządzane są przez dedykowaną stronę.
          </p>
          <Link
            href="/settings/templates"
            className="inline-flex items-center gap-2 mt-3 text-sm text-blue-600 hover:underline font-medium"
          >
            Przejdź do szablonów <ExternalLink className="w-3.5 h-3.5" />
          </Link>
        </div>
      )}

      {activeTab === "onboarding" && (
        <OnboardingSettings />
      )}
    </div>
  );
}

function OnboardingSettings() {
  const [shown, setShown] = useState(false);

  const handleReset = () => {
    localStorage.removeItem("onboarding_completed");
    setShown(true);
    setTimeout(() => {
      window.location.reload();
    }, 1500);
  };

  return (
    <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-6">
      <div className="flex items-start gap-4 mb-6">
        <div className="w-12 h-12 rounded-xl bg-blue-50 dark:bg-blue-900/30 flex items-center justify-center flex-shrink-0">
          <HelpCircle className="w-6 h-6 text-blue-500" />
        </div>
        <div>
          <h3 className="text-base font-bold text-gray-900 dark:text-gray-100">Przewodnik wprowadzający</h3>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
            Pokaż ponownie przewodnik po DynaMinds Nexus
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
          className="flex items-center gap-2 px-4 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-medium hover:bg-blue-700 transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
          Pokaż przewodnik ponownie
        </button>
      )}

      <div className="mt-6 pt-6 border-t border-gray-100 dark:border-gray-700">
        <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">Skróty klawiszowe</h4>
        <div className="grid grid-cols-2 gap-2 text-xs text-gray-600 dark:text-gray-400">
          <div className="flex justify-between p-2 bg-gray-50 dark:bg-gray-700 rounded-lg">
            <span>Wyszukiwanie</span>
            <kbd className="font-mono bg-white dark:bg-gray-600 px-1.5 py-0.5 rounded border border-gray-200 dark:border-gray-500">⌘K</kbd>
          </div>
          <div className="flex justify-between p-2 bg-gray-50 dark:bg-gray-700 rounded-lg">
            <span>Dodaj kandydata</span>
            <kbd className="font-mono bg-white dark:bg-gray-600 px-1.5 py-0.5 rounded border border-gray-200 dark:border-gray-500">⌘⇧C</kbd>
          </div>
          <div className="flex justify-between p-2 bg-gray-50 dark:bg-gray-700 rounded-lg">
            <span>Dodaj ofertę</span>
            <kbd className="font-mono bg-white dark:bg-gray-600 px-1.5 py-0.5 rounded border border-gray-200 dark:border-gray-500">⌘⇧J</kbd>
          </div>
          <div className="flex justify-between p-2 bg-gray-50 dark:bg-gray-700 rounded-lg">
            <span>Skróty</span>
            <kbd className="font-mono bg-white dark:bg-gray-600 px-1.5 py-0.5 rounded border border-gray-200 dark:border-gray-500">?</kbd>
          </div>
        </div>
      </div>
    </div>
  );
}
