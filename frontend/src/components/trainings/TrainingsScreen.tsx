"use client";

import { useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Plus } from "lucide-react";

import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TabbedNav, type TabbedNavItem } from "@/components/ds/TabbedNav";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  downloadTrainingPath,
  trainingMediaUrl,
  trainingPaths,
  useCompanySignatureFor,
  useCloseMarketPanel,
  useMarketPortalSwitch,
  useMarketTrainerApplications,
  useMarketTrainerStatus,
  useOpenMarketPanel,
  useSaveMarketPortalSwitch,
  usePendingSignatures,
  useRateTraining,
  useRegistration,
  searchTranscript,
  useSaveTrainingSettings,
  useTrainerApplications,
  useTrainingLibrary,
  useTrainingList,
  useTrainingSettings,
  useTrainingsMe,
  type TrainingsMe,
} from "@/lib/api/trainings";
import { useUrlTab } from "@/lib/url-tab";
import { resolveViewState } from "@/lib/view-state";
import { hasRole, useAuthStore } from "@/store/auth";

import { MarketTrainerCandidates } from "./MarketTrainerCandidates";
import { MARKET_STATUS_LABEL } from "./market-trainer-model";
import { NoveltyLessonsTab } from "./NoveltyLessonsTab";
import { TrainingCalendar } from "./TrainingCalendar";
import { TrainingLibrary } from "./TrainingLibrary";
import { warsawToday } from "./training-model";
import { PendingSignatures, TrainerApplications, TrainingRegister } from "./TrainingRegister";
import { useRunAction } from "./use-run-action";

// „library” zostaje jako stary adres zakładki nagrań (linki sprzed 0697).
const TABS = ["calendar", "recordings", "library", "nowosci", "organize", "applications", "sign"] as const;
type Tab = (typeof TABS)[number];

function QueryGate({
  query,
  isEmpty,
  empty,
  children,
}: {
  query: { isLoading: boolean; isError: boolean; error: unknown; isSuccess: boolean; refetch: () => unknown };
  isEmpty: boolean;
  empty: React.ReactNode;
  children: React.ReactNode;
}) {
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty,
  });
  if (state === "loading") return <p className="text-sm text-muted-foreground">Ładowanie…</p>;
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <QueryStateNotice state={state} onRetry={() => query.refetch()} />;
  }
  if (state === "empty") return <>{empty}</>;
  return <>{children}</>;
}

function CalendarTab() {
  const library = useTrainingLibrary();
  const registration = useRegistration();
  const run = useRunAction();
  return (
    <QueryGate query={library} isEmpty={false} empty={null}>
      {library.data ? (
        <TrainingCalendar
          live={library.data.live}
          today={warsawToday()}
          busy={registration.isPending}
          onRegister={(id, join) =>
            run(
              () => registration.mutateAsync({ id, join }),
              join ? "Zapisano. Zaproszenie trafi do Twojego kalendarza." : "Wypisano ze szkolenia.",
              "Nie udało się zmienić zapisu.",
            )
          }
        />
      ) : null}
    </QueryGate>
  );
}

function LibraryTab() {
  const library = useTrainingLibrary();
  const rate = useRateTraining();
  const run = useRunAction();
  return (
    <QueryGate query={library} isEmpty={false} empty={null}>
      {library.data ? (
        <TrainingLibrary
          library={library.data}
          onSearchTranscript={async (id, q) => {
            try {
              return await searchTranscript(id, q);
            } catch {
              return null;
            }
          }}
          onRate={(id, rating) =>
            run(
              () => rate.mutateAsync({ id, rating, comment: "" }),
              "Dziękujemy za ocenę.",
              "Nie udało się zapisać oceny.",
            )
          }
          getMediaUrl={async (file) => {
            try {
              return await trainingMediaUrl(file.id);
            } catch {
              return null;
            }
          }}
          onDownload={(file) => {
            void run(
              () => downloadTrainingPath(trainingPaths.libraryFile(file.id), file.file_name),
              null,
              "Nie udało się pobrać pliku.",
            );
          }}
        />
      ) : null}
    </QueryGate>
  );
}

function SharePointSettings() {
  const settings = useTrainingSettings();
  const save = useSaveTrainingSettings();
  const run = useRunAction();
  const [url, setUrl] = useState<string | null>(null);
  const value = url ?? settings.data?.share_url ?? "";
  return (
    <Card size="sm" className="space-y-2 p-4">
      <h2 className="text-sm font-semibold">Folder na pliki szkoleń (SharePoint)</h2>
      {settings.isError ? (
        <p role="alert" className="text-xs text-destructive">
          Nie udało się odczytać ustawienia folderu.
        </p>
      ) : settings.isSuccess ? (
        <p className="text-xs text-muted-foreground">
          {settings.data.sharepoint
            ? "Pliki trafiają do folderu SharePointa."
            : "Folder nie jest ustawiony: pliki zostają na serwerze NEXUSA."}
        </p>
      ) : null}
      <form
        className="flex flex-wrap gap-2"
        onSubmit={async (event) => {
          event.preventDefault();
          const ok = await run(
            () => save.mutateAsync(value.trim()),
            "Zapisano folder na pliki szkoleń.",
            "Nie udało się zapisać folderu.",
          );
          if (ok) setUrl(null);
        }}
      >
        <Input
          aria-label="Link do folderu SharePointa"
          placeholder="https://…sharepoint.com/…"
          className="min-w-0 flex-1"
          value={value}
          onChange={(event) => setUrl(event.target.value)}
        />
        <Button type="submit" size="sm" variant="outline" disabled={save.isPending || value.trim().length < 10}>
          Zapisz folder
        </Button>
      </form>
    </Card>
  );
}

function OrganizeTab({ isAdmin }: { isAdmin: boolean }) {
  const list = useTrainingList();
  return (
    <div className="space-y-4">
      <QueryGate
        query={list}
        isEmpty={(list.data ?? []).length === 0}
        empty={
          <p className="rounded-lg border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
            Nie ma jeszcze szkoleń. Zamów pierwsze ze zgłoszenia trenera albo dla pracownika.
          </p>
        }
      >
        <TrainingRegister rows={list.data ?? []} />
      </QueryGate>
      {isAdmin ? <SharePointSettings /> : null}
    </div>
  );
}

/** Włącznik wejścia trenerów z rynku (0807): stan widzi TCM, przełącza admin. */
function MarketPortalSwitch({ isAdmin }: { isAdmin: boolean }) {
  const state = useMarketPortalSwitch();
  const save = useSaveMarketPortalSwitch();
  const run = useRunAction();
  if (!state.isSuccess) return null;
  const enabled = state.data;
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs">
      <p className="text-muted-foreground">
        <span className="font-medium text-foreground">
          Panel trenerów z rynku: {enabled ? "włączony" : "wyłączony"}.
        </span>{" "}
        {enabled
          ? "Otwarcie panelu wysyła trenerowi link."
          : "Panel możesz otworzyć, ale link wyjdzie dopiero po włączeniu przez administratora."}
      </p>
      {isAdmin ? (
        <Button
          size="sm"
          variant="outline"
          disabled={save.isPending}
          onClick={() =>
            void run(
              () => save.mutateAsync(!enabled),
              enabled ? "Wyłączono panel trenerów z rynku." : "Włączono panel trenerów z rynku.",
              "Nie udało się zmienić ustawienia.",
            )
          }
        >
          {enabled ? "Wyłącz" : "Włącz"}
        </Button>
      ) : null}
    </div>
  );
}

/** Kandydaci na trenerów spoza B2B ze strony (0806); decyduje TCM. */
function MarketCandidatesSection({ isAdmin }: { isAdmin: boolean }) {
  const market = useMarketTrainerApplications();
  const status = useMarketTrainerStatus();
  const openPanel = useOpenMarketPanel();
  const closePanel = useCloseMarketPanel();
  const run = useRunAction();
  return (
    <>
    <MarketPortalSwitch isAdmin={isAdmin} />
    <QueryGate
      query={market}
      isEmpty={(market.data ?? []).length === 0}
      empty={
        <p className="rounded-lg border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
          Nie ma zgłoszeń ze strony. Trenerzy spoza B2B zgłaszają się na b2bnetwork.pl w „Zostań
          trenerem”.
        </p>
      }
    >
      <MarketTrainerCandidates
        applications={market.data ?? []}
        busy={status.isPending || openPanel.isPending || closePanel.isPending}
        onChange={(application, to, note) => {
          void run(
            () => status.mutateAsync({ id: application.id, status: to, note }),
            `${application.full_name}: ${MARKET_STATUS_LABEL[to].toLowerCase()}.`,
            "Nie udało się zmienić stanu zgłoszenia.",
          );
        }}
        onOpenPanel={(application, body) =>
          run(
            () => openPanel.mutateAsync({ id: application.id, body }),
            (result) =>
              result.invite === "sent"
                ? `Panel otwarty. Link poszedł na ${body.panel_email}.`
                : "Panel otwarty. Link wyjdzie po włączeniu panelu trenerów przez administratora.",
            "Nie udało się otworzyć panelu.",
          )
        }
        onClosePanel={(application) => {
          void run(
            () => closePanel.mutateAsync(application.id),
            `Panel zamknięty: ${application.full_name}.`,
            "Nie udało się zamknąć panelu.",
          );
        }}
      />
    </QueryGate>
    </>
  );
}

function ApplicationsTab({ isAdmin }: { isAdmin: boolean }) {
  return (
    <div className="space-y-8">
      <MarketCandidatesSection isAdmin={isAdmin} />
      <section aria-labelledby="panel-trainers-title" className="space-y-3">
        <h2 id="panel-trainers-title" className="text-base font-semibold text-foreground">
          Konsultanci z panelu
        </h2>
        <PanelApplications />
      </section>
    </div>
  );
}

function PanelApplications() {
  const applications = useTrainerApplications();
  const run = useRunAction();
  return (
    <QueryGate
      query={applications}
      isEmpty={(applications.data ?? []).length === 0}
      empty={
        <p className="rounded-lg border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
          Nie ma zgłoszeń trenerów. Konsultant zgłasza się w panelu: „Zostań trenerem”.
        </p>
      }
    >
      <TrainerApplications
        applications={applications.data ?? []}
        onDownloadSample={(application) => {
          void run(
            () =>
              downloadTrainingPath(
                trainingPaths.sample(application.id),
                application.sample_name ?? "probka",
              ),
            null,
            "Nie udało się pobrać próbki.",
          );
        }}
      />
    </QueryGate>
  );
}

function SignTab() {
  const pending = usePendingSignatures();
  const sign = useCompanySignatureFor();
  const run = useRunAction();
  return (
    <QueryGate
      query={pending}
      isEmpty={(pending.data ?? []).length === 0}
      empty={<p className="text-sm text-muted-foreground">Nic nie czeka na Twój podpis.</p>}
    >
      <PendingSignatures
        items={pending.data ?? []}
        busy={sign.isPending}
        onDownload={(item) => {
          void run(
            () =>
              downloadTrainingPath(trainingPaths.agreementPdf(item.id, "trainer"), "umowa.pdf"),
            null,
            "Nie udało się pobrać umowy.",
          );
        }}
        onSign={(item, file) =>
          run(
            () => sign.mutateAsync({ id: item.id, file }),
            "Umowa podpisana przez obie strony.",
            "Nie udało się wgrać podpisanej umowy.",
          )
        }
      />
    </QueryGate>
  );
}

function tabsFor(
  me: TrainingsMe | undefined,
  pendingCount: number,
  newMarketCount: number,
): TabbedNavItem[] {
  const tabs: TabbedNavItem[] = [
    { value: "calendar", label: "Kalendarz" },
    // Krok lekcji „Szkolenia w NEXUSIE” (novelties.json): z Kalendarza do nagrań.
    { value: "recordings", label: "Nagrania", "data-tour": "trainings.tab.recordings" },
    // Lekcje nowości do powtórki na Poligonie (Igor i Artur, 23.11.2026).
    { value: "nowosci", label: "Nowości w NEXUSIE" },
  ];
  if (me?.can_read) tabs.push({ value: "organize", label: "Organizuję" });
  if (me?.can_manage) {
    tabs.push({
      value: "applications",
      label: "Zgłoszenia trenerów",
      ...(newMarketCount > 0 ? { count: newMarketCount } : {}),
    });
  }
  if (me?.is_company_signer && pendingCount > 0) {
    tabs.push({ value: "sign", label: "Do podpisu", count: pendingCount });
  }
  return tabs;
}

/** „Szkolenia”: biblioteka dla każdego, rejestr dla TCM i Finansów, podpis dla reprezentanta. */
export function TrainingsScreen() {
  const searchParams = useSearchParams();
  const user = useAuthStore((state) => state.user);
  const me = useTrainingsMe();
  const pending = usePendingSignatures(me.data?.is_company_signer === true);
  const [requested, selectTab] = useUrlTab<Tab>({
    requested: searchParams.get("tab"),
    validTabs: TABS,
    defaultTab: "calendar",
  });
  // Licznik nowych zgłoszeń ze strony na zakładce: TCM nie ma dzwonka o zgłoszeniu.
  const market = useMarketTrainerApplications(me.data?.can_manage === true);
  const newMarket = (market.data ?? []).filter((item) => item.status === "new").length;
  const tabs = tabsFor(me.data, pending.data?.length ?? 0, newMarket);
  const asked: Tab = requested === "library" ? "recordings" : requested;
  const current: Tab = tabs.some((tab) => tab.value === asked) ? asked : "calendar";

  return (
    <div className="space-y-4">
      <PageHeader
        title="Szkolenia"
        description="Kalendarz szkoleń na żywo w Teams, nagrania z transkryptem, materiały i lekcje nowości NEXUSA."
        density="compact"
        actions={
          me.data?.can_manage ? (
            <Button asChild>
              <Link href="/trainings/new">
                <Plus className="h-4 w-4" aria-hidden /> Nowe szkolenie
              </Link>
            </Button>
          ) : null
        }
      />
      {me.isError ? (
        <p className="text-xs text-muted-foreground">
          Nie udało się sprawdzić Twoich uprawnień do szkoleń, więc widać samą bibliotekę.
        </p>
      ) : null}
      {tabs.length > 1 ? (
        <TabbedNav
          ariaLabel="Sekcje szkoleń"
          value={current}
          onValueChange={(value) => selectTab(value as Tab)}
          tabs={tabs}
        />
      ) : null}
      {current === "calendar" ? <CalendarTab /> : null}
      {current === "recordings" ? <LibraryTab /> : null}
      {current === "nowosci" ? <NoveltyLessonsTab /> : null}
      {current === "organize" ? <OrganizeTab isAdmin={hasRole(user, "admin")} /> : null}
      {current === "applications" ? <ApplicationsTab isAdmin={hasRole(user, "admin")} /> : null}
      {current === "sign" ? <SignTab /> : null}
    </div>
  );
}
