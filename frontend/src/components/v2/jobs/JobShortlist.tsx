"use client";

import { useEffect, useRef, useState, type InputHTMLAttributes } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowUpRight, Check, Trash2, UserCheck } from "lucide-react";

import api from "@/lib/api";
import {
  shortlistApi,
  type EvaluationStatus,
  type OutreachStatus,
  type ShortlistEntry,
  type ShortlistUpdate,
} from "@/lib/candidate-search-api";
import { useToast } from "@/components/Toast";

/** Ownership-eligible userzy do dropdownu „Właściciel" (ten sam directory co
 *  filtr „Dodany przez"; `/api/users` = OperationalUser, nie admin-only). */
interface OwnerOption {
  id: number;
  name: string;
}

/** ISO → wartość dla <input type="datetime-local"> w czasie LOKALNYM. */
function isoToLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

/** Wartość `<input type="datetime-local">` jako znacznik czasu (`null` = puste). */
function localInputMs(value: string): number | null {
  if (!value) return null;
  const ms = new Date(value).getTime();
  return Number.isNaN(ms) ? null : ms;
}

// Porównania wartości pól — na poziomie modułu, żeby tożsamość funkcji była
// stała (pole trzyma je w zależnościach efektu).
const sameNote = (a: string, b: string) => a.trim() === b.trim();
const sameInstant = (a: string, b: string) => localInputMs(a) === localInputMs(b);

/** Stan pola na serwerze: wartość w formacie pola + wersja wpisu. */
interface FieldServerState {
  value: string;
  version: number;
}

/** Wynik zapisu pola — mówi polu, co zrobić z tym, co wpisał użytkownik. */
type FieldCommitOutcome =
  /** Zapisane — pole pokazuje wartość z odpowiedzi serwera. */
  | ({ status: "saved" } & FieldServerState)
  /**
   * Kolega zmienił TO pole w międzyczasie. Tekst użytkownika zostaje w polu,
   * a pole przyjmuje nową wersję — kolejny świadomy zapis nadpisze zmianę
   * kolegi, wiedząc o niej.
   */
  | ({ status: "conflict" } & FieldServerState)
  /** Inny błąd — tekst i baza edycji zostają; kolejny blur ponowi zapis. */
  | { status: "failed" };

interface ServerSyncedInputProps
  extends Omit<
    InputHTMLAttributes<HTMLInputElement>,
    "value" | "defaultValue" | "onChange" | "onFocus" | "onBlur"
  > {
  /** Wartość z serwera w formacie pola (np. lokalny datetime). */
  serverValue: string;
  /** `ShortlistEntry.version` — każda zmiana wpisu na serwerze ją podbija. */
  serverVersion: number;
  /** Czy dwie wartości pola znaczą to samo (np. ta sama chwila w czasie). */
  sameValue: (a: string, b: string) => boolean;
  /**
   * Zapis zmiany UŻYTKOWNIKA. `base` to stan serwera, od którego zaczęła się
   * zmiana (wartość tego pola + wersja wpisu) — serwer odpowie 409, jeśli ktoś
   * zapisał wpis w międzyczasie, zamiast po cichu nadpisać jego zmianę.
   */
  onCommit: (value: string, base: FieldServerState) => Promise<FieldCommitOutcome>;
}

/**
 * Pole tekstowe zapisywane na blur, zsynchronizowane z serwerem.
 *
 * Do 09.2026 notatka i termin były polami NIEKONTROLOWANYMI z wartością
 * z pierwszego renderu, a potem łapały bazę edycji przy WEJŚCIU w pole.
 * Obie wersje gubiły cudzą albo własną pracę:
 *  - Tab z notatki do terminu łapał bazę terminu, zanim wrócił zapis notatki
 *    — własny, wcześniejszy zapis kończył się 409 na polu obok;
 *  - 409 odświeżało listę i pole bez fokusu nadpisywało wpisany tekst.
 * Teraz:
 *  - dopóki pole ma wartość serwera, idzie za serwerem (wartość i wersja);
 *    baza edycji zamarza przy PIERWSZEJ zmianie użytkownika,
 *  - blur bez zmiany (albo z powrotem do stanu wyjścia) NIE zapisuje niczego,
 *  - po 409 tekst użytkownika zostaje w polu — co dalej, decyduje `onCommit`
 *    (cichy rebase, gdy kolega zmienił inne pole; konflikt, gdy to samo).
 */
function ServerSyncedInput({
  serverValue,
  serverVersion,
  sameValue,
  onCommit,
  ...inputProps
}: ServerSyncedInputProps) {
  const [draft, setDraft] = useState(serverValue);
  const draftRef = useRef(serverValue);
  // Najnowszy znany stan serwera: z propsów albo z odpowiedzi własnego zapisu
  // (ta wyprzedza odświeżenie listy — bez tego kolejna zmiana zamroziłaby
  // bazę na wersji sprzed własnego zapisu).
  const knownRef = useRef<FieldServerState>({
    value: serverValue,
    version: serverVersion,
  });
  // Baza bieżącej zmiany; `null` = pole ma wartość serwera i idzie za nim.
  const baseRef = useRef<FieldServerState | null>(null);

  const updateDraft = (value: string) => {
    draftRef.current = value;
    setDraft(value);
  };

  useEffect(() => {
    // Starszy stan niż znany (lista jeszcze nie odświeżona po zapisie) — pomiń.
    if (serverVersion < knownRef.current.version) return;
    knownRef.current = { value: serverValue, version: serverVersion };
    const clean = baseRef.current === null;
    if (clean || sameValue(draftRef.current, serverValue)) {
      // Pole bez zmian idzie za serwerem; zmienione — gdy serwer ma już
      // dokładnie to, co wpisano, pole znów jest „czyste".
      baseRef.current = null;
      draftRef.current = serverValue;
      setDraft(serverValue);
    }
  }, [serverValue, serverVersion, sameValue]);

  const commit = async (value: string, base: FieldServerState) => {
    let outcome: FieldCommitOutcome;
    try {
      outcome = await onCommit(value, base);
    } catch {
      outcome = { status: "failed" };
    }
    if (outcome.status === "failed") return;
    knownRef.current = { value: outcome.value, version: outcome.version };
    if (outcome.status === "saved") {
      baseRef.current = null;
      updateDraft(outcome.value);
      return;
    }
    // Konflikt: tekst zostaje, baza przyjmuje nową wersję — następny zapis
    // nadpisze zmianę kolegi świadomie.
    baseRef.current = { value: outcome.value, version: outcome.version };
  };

  return (
    <input
      {...inputProps}
      value={draft}
      onChange={(e) => {
        const next = e.target.value;
        if (sameValue(next, knownRef.current.value)) {
          baseRef.current = null;
        } else if (baseRef.current === null) {
          baseRef.current = { ...knownRef.current };
        }
        updateDraft(next);
      }}
      onBlur={() => {
        const base = baseRef.current;
        const value = draftRef.current;
        if (
          base === null ||
          sameValue(value, base.value) ||
          sameValue(value, knownRef.current.value)
        ) {
          // Nic do zapisania — pokaż aktualny stan serwera (mógł się zmienić,
          // gdy pole miało fokus) i NIE zapisuj.
          baseRef.current = null;
          updateDraft(knownRef.current.value);
          return;
        }
        void commit(value, base);
      }}
    />
  );
}

/** Klucz zapytania współdzielony z licznikiem w pasku przełącznika — react-query
 *  deduplikuje, więc tablica i licznik czytają jeden fetch. */
export const jobShortlistQueryKey = (jobId: number) =>
  ["job-shortlist", jobId] as const;

// Etykiety PL — model nie ma jeszcze mapy w FE, więc definiujemy ją tu
// (te same wartości enum co w schemas/job_shortlist.py).
const EVALUATION_LABEL: Record<EvaluationStatus, string> = {
  do_oceny: "Do oceny",
  potencjalny: "Potencjalny",
  zatwierdzony: "Zatwierdzony",
  odrzucony: "Odrzucony",
};
const EVALUATION_ORDER: EvaluationStatus[] = [
  "do_oceny",
  "potencjalny",
  "zatwierdzony",
  "odrzucony",
];
const OUTREACH_LABEL: Record<OutreachStatus, string> = {
  nie_kontaktowano: "Nie kontaktowano",
  do_kontaktu: "Do kontaktu",
  kontakt_w_toku: "Kontakt w toku",
  zainteresowany: "Zainteresowany",
  brak_zainteresowania: "Brak zainteresowania",
};

// Ton segmentu oceny — kolor niesie znaczenie (zatwierdzony/odrzucony), reszta
// neutralna. Tokeny, nie hardcode.
function evalActiveClass(status: EvaluationStatus): string {
  if (status === "zatwierdzony") return "bg-success text-success-foreground";
  if (status === "odrzucony") return "bg-destructive text-destructive-foreground";
  if (status === "potencjalny") return "bg-info text-info-foreground";
  return "bg-primary text-primary-foreground";
}

function formatDatePl(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit" });
}

function isPast(iso: string | null | undefined): boolean {
  if (!iso) return false;
  const d = new Date(iso);
  return !Number.isNaN(d.getTime()) && d.getTime() < Date.now();
}

/** Pola tekstowe wpisu zapisywane na blur (`ServerSyncedInput`). */
type ShortlistTextField = "note" | "next_action_at";

/** Biernik do komunikatu o konflikcie — „zmienił w międzyczasie …". */
const TEXT_FIELD_LABEL: Record<ShortlistTextField, string> = {
  note: "notatkę",
  next_action_at: "termin następnej akcji",
};

/** Wartość pola wpisu w formacie `<input>` (datetime lokalny dla terminu). */
function fieldInputValue(entry: ShortlistEntry, field: ShortlistTextField): string {
  return field === "note"
    ? (entry.note ?? "")
    : isoToLocalInput(entry.next_action_at);
}

/** Wartość pola z `<input>` → fragment `PATCH`-a. */
function fieldPatch(
  field: ShortlistTextField,
  value: string,
): Pick<ShortlistUpdate, "note" | "next_action_at"> {
  return field === "note"
    ? { note: value.trim() || null }
    : { next_action_at: value ? new Date(value).toISOString() : null };
}

function httpStatusOf(e: unknown): number | undefined {
  return (e as { response?: { status?: number } })?.response?.status;
}

interface JobShortlistProps {
  jobId: number;
  readOnly?: boolean;
}

/**
 * Tablica shortlisty oferty — powierzchnia zarządzania wpisami z
 * `job_shortlist_entries` (ocena → kontakt → promocja do pipeline'u).
 *
 * Zapisy chroni blokada optymistyczna (`version`): równoległy zapis kończy się
 * 409, zamiast po cichu nadpisać cudzą decyzję. Przy ocenie, kontakcie
 * i właścicielu odświeżamy listę i prosimy o ponowienie; przy notatce
 * i terminie wpisany tekst ZOSTAJE w polu (patrz `fieldMutation`). Promocja
 * przechodzi przez tę samą bramkę dopuszczalności co ranking — jej 409
 * pokazujemy z powodem po polsku.
 */
export function JobShortlist({ jobId, readOnly = false }: JobShortlistProps) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();

  const { data, isLoading, isError, isSuccess, refetch } = useQuery({
    queryKey: jobShortlistQueryKey(jobId),
    queryFn: () => shortlistApi.list(jobId),
    staleTime: 30_000,
  });

  const entries = data ?? [];

  // Directory ownership-eligible userów. Ładowany ZAWSZE (także w readOnly),
  // bo readOnly renderuje nazwę właściciela z tej listy — z `enabled:!readOnly`
  // spadała do „#id". Współdzielony queryKey z filtrem „Dodany przez" +
  // 5-min staleTime → react-query i tak nie dubluje fetcha (PR #1374 review).
  const { data: owners = [] } = useQuery<OwnerOption[]>({
    queryKey: ["users-directory"],
    queryFn: () => api.get("/api/users").then((r) => r.data),
    staleTime: 5 * 60_000,
  });
  const ownerName = (id: number | null | undefined): string | null => {
    if (id == null) return null;
    const u = owners.find((o) => o.id === id);
    return u ? u.name : `#${id}`;
  };

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: jobShortlistQueryKey(jobId) });

  const patchMutation = useMutation({
    mutationFn: (args: {
      entry: ShortlistEntry;
      patch: Partial<
        Pick<
          ShortlistEntry,
          | "evaluation_status"
          | "outreach_status"
          | "owner_id"
          | "note"
          | "next_action_at"
        >
      >;
    }) =>
      shortlistApi.update(args.entry.id, {
        version: args.entry.version,
        ...args.patch,
      }),
    onSuccess: () => invalidate(),
    onError: (e: unknown) => {
      const status = (e as { response?: { status?: number } })?.response?.status;
      if (status === 409) {
        showError("Ktoś zapisał ten wpis równolegle — odświeżam, spróbuj ponownie.");
        void refetch();
      } else {
        showError("Nie udało się zapisać zmiany.");
      }
    },
  });

  // Świeży stan wpisu — po 409 trzeba wiedzieć, CO zmieniło się na serwerze.
  // Lista trafia też do cache, żeby reszta wiersza pokazała zmianę kolegi.
  const fetchFreshEntry = async (entryId: number): Promise<ShortlistEntry | null> => {
    const fresh = await shortlistApi.list(jobId);
    queryClient.setQueryData(jobShortlistQueryKey(jobId), fresh);
    return fresh.find((e) => e.id === entryId) ?? null;
  };

  // Zapis notatki / terminu (`ServerSyncedInput`). 409 NIE wyrzuca wpisanego
  // tekstu: gdy kolega zmienił INNE pole wpisu (albo to był własny wcześniejszy
  // zapis — Tab z pola do pola), to pole wciąż ma wartość, od której zaczęła
  // się edycja, więc zapis powtarzamy RAZ na nowej wersji. Gdy zmienił TO
  // pole — tekst zostaje w polu, toast mówi, co się stało, a pole przyjmuje
  // nową wersję, więc następny świadomy zapis nadpisze zmianę kolegi.
  const fieldMutation = useMutation({
    mutationFn: async ({
      entry,
      field,
      value,
      base,
    }: {
      entry: ShortlistEntry;
      field: ShortlistTextField;
      value: string;
      base: FieldServerState;
    }): Promise<FieldCommitOutcome> => {
      const same = field === "note" ? sameNote : sameInstant;
      const save = async (version: number): Promise<FieldCommitOutcome> => {
        const row = await shortlistApi.update(entry.id, {
          version,
          ...fieldPatch(field, value),
        });
        void invalidate();
        return {
          status: "saved",
          value: fieldInputValue(row, field),
          version: row.version,
        };
      };
      const failed = (message: string): FieldCommitOutcome => {
        showError(message);
        return { status: "failed" };
      };
      const fresh = async (): Promise<ShortlistEntry | null | "error"> => {
        try {
          return await fetchFreshEntry(entry.id);
        } catch {
          return "error";
        }
      };

      try {
        return await save(base.version);
      } catch (e) {
        if (httpStatusOf(e) !== 409) {
          return failed("Nie udało się zapisać zmiany — Twój tekst został w polu.");
        }
      }

      let current = await fresh();
      if (current === "error" || current === null) {
        return failed(
          current === null
            ? "Tego wpisu nie ma już na shortliście."
            : "Nie udało się odświeżyć wpisu — Twój tekst został w polu.",
        );
      }
      if (same(fieldInputValue(current, field), base.value)) {
        // To pole się nie zmieniło — zmiana kolegi dotyczyła innego pola.
        try {
          return await save(current.version);
        } catch (e) {
          if (httpStatusOf(e) !== 409) {
            return failed("Nie udało się zapisać zmiany — Twój tekst został w polu.");
          }
        }
        current = await fresh();
        if (current === "error" || current === null) {
          return failed(
            current === null
              ? "Tego wpisu nie ma już na shortliście."
              : "Nie udało się odświeżyć wpisu — Twój tekst został w polu.",
          );
        }
        if (same(fieldInputValue(current, field), base.value)) {
          showError(
            "Ten wpis zmienia się właśnie równolegle — Twój tekst został w polu. " +
              "Wyjdź z pola jeszcze raz, żeby go zapisać.",
          );
          return {
            status: "conflict",
            value: fieldInputValue(current, field),
            version: current.version,
          };
        }
      }
      showError(
        `Ktoś inny zmienił w międzyczasie ${TEXT_FIELD_LABEL[field]} w tym wpisie — ` +
          "Twój tekst został w polu. Wyjdź z pola jeszcze raz, żeby świadomie " +
          "zapisać go zamiast tamtej zmiany.",
      );
      return {
        status: "conflict",
        value: fieldInputValue(current, field),
        version: current.version,
      };
    },
  });

  const promoteMutation = useMutation({
    mutationFn: (entry: ShortlistEntry) => shortlistApi.promote(entry.id),
    onSuccess: (res, entry) => {
      const name = `${entry.candidate_name ?? ""} ${entry.candidate_lastname ?? ""}`.trim();
      showSuccess(
        res.already_in_pipeline || res.already_promoted
          ? `${name} jest już w pipeline`
          : `${name} — przeniesiono do pipeline`,
      );
      void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      invalidate();
    },
    onError: (e: unknown) => {
      // Bramka dopuszczalności zwraca 409 z powodem po polsku (detail).
      const detail = (e as { response?: { data?: { detail?: string } } })?.response
        ?.data?.detail;
      showError(detail || "Nie udało się przenieść do pipeline.");
    },
  });

  const removeMutation = useMutation({
    mutationFn: (entry: ShortlistEntry) => shortlistApi.remove(entry.id),
    onSuccess: () => invalidate(),
    onError: () => showError("Nie udało się usunąć wpisu."),
  });

  // Limbo między retry TanStack Query (isLoading=false, isError=false,
  // data=undefined) też traktujemy jak ładowanie — inaczej `entries=[]` mignęłoby
  // pustym stanem, zanim dane dojdą (znany gotcha z CLAUDE.md: pusty stan wisi
  // na `isSuccess`, nie na `!isLoading`).
  if (isLoading || (!isSuccess && !isError)) {
    return (
      <div className="flex flex-col items-center py-12 text-muted-foreground gap-3">
        <div className="w-7 h-7 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        <p className="text-sm">Wczytywanie shortlisty…</p>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex flex-col items-center py-12 text-muted-foreground gap-2">
        <AlertCircle className="w-10 h-10 text-destructive" />
        <p className="text-sm">Nie udało się wczytać shortlisty</p>
        <button
          onClick={() => refetch()}
          className="text-sm text-primary hover:underline mt-1"
        >
          Spróbuj ponownie
        </button>
      </div>
    );
  }

  if (isSuccess && entries.length === 0) {
    return (
      <div className="flex flex-col items-center py-12 text-muted-foreground gap-2">
        <UserCheck className="w-12 h-12 opacity-30" />
        <p className="text-sm">Shortlista jest pusta</p>
        <p className="text-xs text-muted-foreground">
          Dodaj kandydatów z zakładki „Ranking" przyciskiem „Na shortlistę".
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {entries.map((entry) => {
        const fullName =
          `${entry.candidate_name ?? ""} ${entry.candidate_lastname ?? ""}`.trim() ||
          `Kandydat #${entry.candidate_id}`;
        // Zajętość PER WIERSZ, nie globalna: mutacje są współdzielone między
        // wpisami, więc zakres po `variables` — inaczej promocja wpisu A
        // zamrażałaby cały stół. (PR #1369 review.)
        const busy =
          (patchMutation.isPending &&
            patchMutation.variables?.entry.id === entry.id) ||
          (fieldMutation.isPending &&
            fieldMutation.variables?.entry.id === entry.id) ||
          (promoteMutation.isPending &&
            promoteMutation.variables?.id === entry.id) ||
          (removeMutation.isPending && removeMutation.variables?.id === entry.id);
        const promoted = Boolean(entry.promoted_to_pipeline_at);
        const overdue = isPast(entry.next_action_at);
        return (
          <div
            key={entry.id}
            className="flex flex-col gap-2 rounded-xl border border-border bg-card dark:bg-muted p-3"
          >
            {/* Górny rząd: kandydat + ocena + kontakt + akcje */}
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              {/* Kandydat + snapshot */}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-semibold text-foreground">
                    {fullName}
                  </span>
                  {entry.score_snapshot != null && (
                    <span
                      className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[11px] font-semibold tabular-nums text-muted-foreground"
                      title="Wynik dopasowania z chwili dodania"
                    >
                      {entry.score_snapshot}
                    </span>
                  )}
                </div>
              </div>

              {/* Ocena — segment 4 */}
              <div className="flex rounded-lg border border-border bg-muted/40 p-0.5">
                {EVALUATION_ORDER.map((status) => {
                  const active = entry.evaluation_status === status;
                  return (
                    <button
                      key={status}
                      type="button"
                      disabled={readOnly || busy || active}
                      onClick={() =>
                        patchMutation.mutate({ entry, patch: { evaluation_status: status } })
                      }
                      className={
                        "px-2 py-1 text-[11px] rounded-md whitespace-nowrap transition-colors disabled:cursor-default " +
                        (active
                          ? evalActiveClass(status)
                          : "text-muted-foreground hover:bg-accent")
                      }
                    >
                      {EVALUATION_LABEL[status]}
                    </button>
                  );
                })}
              </div>

              {/* Kontakt — select 5 */}
              <select
                value={entry.outreach_status}
                disabled={readOnly || busy}
                onChange={(e) =>
                  patchMutation.mutate({
                    entry,
                    patch: { outreach_status: e.target.value as OutreachStatus },
                  })
                }
                className="h-8 rounded-lg border border-border bg-card px-2 text-xs text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary disabled:opacity-50"
                aria-label={`Status kontaktu: ${fullName}`}
              >
                {(Object.keys(OUTREACH_LABEL) as OutreachStatus[]).map((s) => (
                  <option key={s} value={s}>
                    {OUTREACH_LABEL[s]}
                  </option>
                ))}
              </select>

              {/* Akcje */}
              {!readOnly && (
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    disabled={busy || promoted}
                    onClick={() => promoteMutation.mutate(entry)}
                    title={promoted ? "Już w pipeline" : "Przenieś do pipeline"}
                    className="inline-flex items-center gap-1 rounded-lg bg-primary px-2.5 py-1.5 text-xs text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-default transition-colors"
                  >
                    {promoted ? (
                      <>
                        <Check className="w-3 h-3" /> W pipeline
                      </>
                    ) : (
                      <>
                        <ArrowUpRight className="w-3 h-3" /> Promuj
                      </>
                    )}
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => removeMutation.mutate(entry)}
                    title="Usuń ze shortlisty"
                    className="inline-flex items-center justify-center rounded-lg border border-border p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50 transition-colors"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              )}
            </div>

            {/* Dolny rząd: właściciel · termin · notatka */}
            {readOnly ? (
              (entry.owner_id != null ||
                entry.next_action_at ||
                entry.note) && (
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border/60 pt-2 text-[11px] text-muted-foreground">
                  {entry.owner_id != null && (
                    <span>Właściciel: {ownerName(entry.owner_id)}</span>
                  )}
                  {entry.next_action_at && (
                    <span className={overdue ? "text-destructive font-medium" : ""}>
                      {overdue ? "Po terminie: " : "Termin: "}
                      {formatDatePl(entry.next_action_at)}
                    </span>
                  )}
                  {entry.note && (
                    <span className="min-w-0 flex-1 truncate">Notatka: {entry.note}</span>
                  )}
                </div>
              )
            ) : (
              <div className="flex flex-col gap-2 border-t border-border/60 pt-2 sm:flex-row sm:items-center">
                {/* Właściciel */}
                <select
                  value={entry.owner_id ?? ""}
                  disabled={busy}
                  onChange={(e) =>
                    patchMutation.mutate({
                      entry,
                      patch: {
                        owner_id: e.target.value ? Number(e.target.value) : null,
                      },
                    })
                  }
                  className="h-8 shrink-0 rounded-lg border border-border bg-card px-2 text-xs text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary disabled:opacity-50"
                  aria-label={`Właściciel: ${fullName}`}
                >
                  <option value="">— nieprzypisane —</option>
                  {owners.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.name}
                    </option>
                  ))}
                </select>

                {/* Termin następnej akcji — zapis na blur, nie na każdy krok
                    (datetime-local emituje onChange przy każdej cyfrze/kliknięciu
                    strzałki; kolejne PATCH-e z tą samą `version` dawały 409).
                    Pole zsynchronizowane z serwerem — patrz `ServerSyncedInput`. */}
                <ServerSyncedInput
                  type="datetime-local"
                  serverValue={isoToLocalInput(entry.next_action_at)}
                  serverVersion={entry.version}
                  sameValue={sameInstant}
                  disabled={busy}
                  onCommit={(value, base) =>
                    fieldMutation.mutateAsync({
                      entry,
                      field: "next_action_at",
                      value,
                      base,
                    })
                  }
                  className={
                    "h-8 shrink-0 rounded-lg border bg-card px-2 text-xs focus:outline-hidden focus:ring-2 focus:ring-primary disabled:opacity-50 " +
                    (overdue
                      ? "border-destructive/50 text-destructive"
                      : "border-border text-foreground")
                  }
                  aria-label={`Termin następnej akcji: ${fullName}`}
                />

                {/* Notatka — zapis na blur, wyłącznie gdy UŻYTKOWNIK ją zmienił. */}
                <ServerSyncedInput
                  type="text"
                  serverValue={entry.note ?? ""}
                  serverVersion={entry.version}
                  sameValue={sameNote}
                  disabled={busy}
                  placeholder="Notatka…"
                  onCommit={(value, base) =>
                    fieldMutation.mutateAsync({
                      entry,
                      field: "note",
                      value,
                      base,
                    })
                  }
                  className="h-8 min-w-0 flex-1 rounded-lg border border-border bg-card px-2 text-xs text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary disabled:opacity-50"
                  aria-label={`Notatka: ${fullName}`}
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
