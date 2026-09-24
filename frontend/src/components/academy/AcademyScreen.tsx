"use client";

/**
 * Akademia — kontener ekranu programu: zapytania, akcje i zakładka w adresie
 * (`?view=`). Cała prezentacja w `AcademyWorkspace`.
 */

import * as React from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { EmptyState } from "@/components/ds/EmptyState";
import { useToast } from "@/components/Toast";
import { bulkFailureMessage } from "@/lib/academy-flow";
import { apiErrorMessage } from "@/lib/api-error";
import {
  academyApi,
  academyKeys,
  type AcademyApplication,
  type ActionBody,
} from "@/lib/api/academy";
import { downloadBlob } from "@/lib/authenticated-files";
import { ACADEMY_POLL_MS } from "@/lib/polling";
import { useAuthStore } from "@/store/auth";

import { ACADEMY_VIEWS, AcademyWorkspace, type AcademyHandlers, type AcademyView } from "./AcademyWorkspace";

function parseView(value: string | null): AcademyView {
  return (ACADEMY_VIEWS as readonly string[]).includes(value ?? "")
    ? (value as AcademyView)
    : "edition";
}

export function AcademyScreen({ programId }: { programId: number }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const view = parseView(params.get("view"));
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [busyIds, setBusyIds] = React.useState<ReadonlySet<number>>(new Set());
  const [syncing, setSyncing] = React.useState(false);
  const [now, setNow] = React.useState(() => new Date());
  const currentUserName = useAuthStore((state) => state.user?.name ?? "");

  React.useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(timer);
  }, []);

  const program = useQuery({
    queryKey: academyKeys.program(programId),
    queryFn: () => academyApi.program(programId),
  });
  const applications = useQuery({
    queryKey: academyKeys.applications(programId),
    queryFn: () => academyApi.applications(programId),
    refetchInterval: ACADEMY_POLL_MS,
  });
  const sessions = useQuery({
    queryKey: academyKeys.sessions(programId),
    queryFn: () => academyApi.sessions(programId),
    refetchInterval: ACADEMY_POLL_MS,
  });

  const setView = (next: AcademyView) => {
    const search = new URLSearchParams(params.toString());
    if (next === "edition") search.delete("view");
    else search.set("view", next);
    const qs = search.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };

  const refreshAll = () =>
    queryClient.invalidateQueries({ queryKey: academyKeys.all });

  const replaceRow = (row: AcademyApplication) => {
    queryClient.setQueryData(
      academyKeys.applications(programId),
      (old: { items: AcademyApplication[]; counts: Record<string, number> } | undefined) =>
        old ? { ...old, items: old.items.map((a) => (a.id === row.id ? row : a)) } : old,
    );
  };

  const handlers: AcademyHandlers = {
    act: async (app, body) => {
      setBusyIds((prev) => new Set(prev).add(app.id));
      try {
        const row = await academyApi.action(app.id, body);
        replaceRow(row);
        if (body.action === "schedule" || body.action === "absent" || body.action === "give_task") {
          void queryClient.invalidateQueries({ queryKey: academyKeys.sessions(programId) });
        }
        void queryClient.invalidateQueries({ queryKey: academyKeys.program(programId) });
        return true;
      } catch (err) {
        showError(apiErrorMessage(err, "Nie udało się zapisać zmiany."));
        void queryClient.invalidateQueries({ queryKey: academyKeys.applications(programId) });
        return false;
      } finally {
        setBusyIds((prev) => {
          const next = new Set(prev);
          next.delete(app.id);
          return next;
        });
      }
    },
    bulk: async (ids: number[], body: ActionBody) => {
      try {
        const result = await academyApi.bulk(programId, ids, body);
        const failure = bulkFailureMessage(body.action, result.failed);
        if (failure) showError(failure);
        if (result.done.length) showSuccess(`Zapisano dla ${result.done.length} os.`);
      } catch (err) {
        showError(apiErrorMessage(err, "Nie udało się zapisać zmian."));
      } finally {
        await refreshAll();
      }
    },
    sync: async () => {
      setSyncing(true);
      try {
        const result = await academyApi.sync(programId);
        if (result.busy) {
          showSuccess(result.message ?? "Pobieranie już trwa.");
        } else {
          const parts = [`nowych: ${result.new ?? 0}`];
          if (result.reapplied) parts.push(`wykluczonych, którzy wrócili: ${result.reapplied}`);
          if (result.returned) parts.push(`powrotów: ${result.returned}`);
          showSuccess(
            `Pobrano zgłoszenia — ${parts.join(", ")}. Luna sortuje je w tle; lista odświeży się sama.`,
          );
          // Sortowanie to kilka–kilkadziesiąt sekund — dociągnij wynik dwa razy.
          for (const delay of [20_000, 60_000]) {
            setTimeout(() => {
              void queryClient.invalidateQueries({ queryKey: academyKeys.applications(programId) });
            }, delay);
          }
        }
      } catch (err) {
        showError(apiErrorMessage(err, "Nie udało się pobrać zgłoszeń."));
      } finally {
        setSyncing(false);
        await refreshAll();
      }
    },
    rhythm: async (input) => {
      try {
        const { created } = await academyApi.rhythm(programId, input);
        showSuccess(created ? `Dodano terminów: ${created}.` : "Te terminy już istnieją.");
      } catch (err) {
        showError(apiErrorMessage(err, "Nie udało się dodać terminów."));
      } finally {
        await queryClient.invalidateQueries({ queryKey: academyKeys.sessions(programId) });
      }
    },
    createSession: async (startsAtIso, location) => {
      try {
        await academyApi.createSession(programId, { starts_at: startsAtIso, location });
        showSuccess("Dodano termin.");
      } catch (err) {
        showError(apiErrorMessage(err, "Nie udało się dodać terminu."));
      } finally {
        await queryClient.invalidateQueries({ queryKey: academyKeys.sessions(programId) });
      }
    },
    cancelSession: async (id) => {
      try {
        await academyApi.updateSession(id, { cancelled: true });
      } catch (err) {
        showError(apiErrorMessage(err, "Nie udało się odwołać terminu."));
      } finally {
        await queryClient.invalidateQueries({ queryKey: academyKeys.sessions(programId) });
      }
    },
    saveProgram: async (patch) => {
      try {
        await academyApi.updateProgram(programId, patch);
        showSuccess("Zapisano ustawienia.");
      } catch (err) {
        showError(apiErrorMessage(err, "Nie udało się zapisać ustawień."));
      } finally {
        await refreshAll();
      }
    },
    addSource: async (jobId, since) => {
      try {
        await academyApi.addSource(programId, jobId, since);
        showSuccess("Podpięto ogłoszenie — zgłoszenia pojawią się po pobraniu.");
      } catch (err) {
        showError(apiErrorMessage(err, "Nie udało się podpiąć ogłoszenia."));
      } finally {
        await queryClient.invalidateQueries({ queryKey: academyKeys.program(programId) });
      }
    },
    removeSource: async (jobId) => {
      try {
        await academyApi.removeSource(programId, jobId);
      } catch (err) {
        showError(apiErrorMessage(err, "Nie udało się odpiąć ogłoszenia."));
      } finally {
        await queryClient.invalidateQueries({ queryKey: academyKeys.program(programId) });
      }
    },
    searchJobs: (q) => academyApi.searchJobs(q),
    downloadDocuments: async (app, body) => {
      try {
        const { blob, filename } = await academyApi.documents(app.id, body);
        downloadBlob(blob, filename);
        return true;
      } catch (err) {
        showError(apiErrorMessage(err, "Nie udało się przygotować dokumentów."));
        return false;
      }
    },
  };

  if (program.isError || applications.isError) {
    return (
      <EmptyState
        title="Nie udało się wczytać akademii"
        description={apiErrorMessage(program.error ?? applications.error, "Spróbuj odświeżyć stronę.")}
      />
    );
  }
  if (!program.isSuccess || !applications.isSuccess) {
    return <p className="p-6 text-sm text-muted-foreground">Wczytuję akademię…</p>;
  }

  return (
    <AcademyWorkspace
      program={program.data}
      apps={applications.data.items}
      sessions={sessions.data ?? []}
      sessionsState={{
        loading: sessions.isPending,
        // Nieudane odświeżenie przy wczytanych terminach zostawia je na
        // ekranie; błąd zastępuje listę tylko, gdy nic jeszcze nie przyszło.
        error:
          sessions.isError && sessions.data === undefined
            ? apiErrorMessage(sessions.error, "Spróbuj ponownie.")
            : null,
        onRetry: () => void sessions.refetch(),
      }}
      counts={applications.data.counts}
      total={applications.data.total ?? null}
      view={view}
      onViewChange={setView}
      handlers={handlers}
      busyIds={busyIds}
      syncing={syncing}
      now={now}
      currentUserName={currentUserName}
    />
  );
}
