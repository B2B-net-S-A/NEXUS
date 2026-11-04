"use client";

import { useEffect, useMemo, useState } from "react";
import { CompetenceCategoryName } from "@/components/v2/CompetenceCategoryBadge";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Search,
  Loader2,
  UserPlus,
  X,
  AlertCircle,
  Check,
  Phone,
  Mail,
  ExternalLink,
  Users,
  GitMerge,
  RotateCcw,
} from "lucide-react";
import {
  candidateSearchApi,
  proposalsBulkApi,
  type BulkClosedCard,
  type CandidateSearchItem,
  type BulkProposalsResponse,
  type InJobMatch,
  type SearchTextInterpretation,
} from "@/lib/candidate-search-api";
import { useToast } from "@/components/Toast";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";
import { AVATAR_COLORS } from "@/lib/colors";
import { formatCandidateLocation } from "@/components/v2/pages/candidate-list-helpers";
import { assignErrorMessage } from "@/lib/assign-error";
import { eligibilityBadgeClass } from "@/lib/conflicts";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { EmploymentPill } from "@/components/ds/EmploymentMarker";
import {
  ADD_ANYWAY_HINT,
  EmployedPeopleNotice,
  type EmployedPerson,
} from "@/components/v2/employment/EmploymentNotice";
import { markerCoversEligibility } from "@/lib/employment-marker";
import { countPl } from "@/lib/plural-pl";
import { useAuthStore } from "@/store/auth";
import { useCapability } from "@/hooks/useCapability";
import { usePipelineMoveCore } from "@/hooks/usePipelineMoveCore";
import { canMergeCandidates } from "@/lib/api/candidateMerge";
import { CandidateMergeDialog } from "@/components/v2/candidate-profile/CandidateMergeDialog";
import {
  restoreLabel,
  restoreMovePayload,
} from "@/components/v2/recruitment/AddToRecruitmentDialog";
import {
  largestHomonymGroup,
  monthLabel,
  phoneMatchesQuery,
  samePhoneLabel,
  samePhoneRefs,
  searchKindLine,
  type SamePhoneRef,
} from "@/components/v2/modals/add-candidates-identity";
import { jobNameText } from "@/lib/job-name-text";

interface Props {
  open: boolean;
  onClose: () => void;
  jobId: number;
  jobTitle: string;
}

function initialsOf(name: string, lastname: string): string {
  const first = (name || "").trim()[0] ?? "";
  const second = (lastname || "").trim()[0] ?? "";
  return (first + second).toUpperCase() || "?";
}

function avatarColorFor(seed: string): string {
  const code = (seed.charCodeAt(0) || 0) + (seed.charCodeAt(1) || 0);
  return AVATAR_COLORS[code % AVATAR_COLORS.length];
}

type ClosedInJob = InJobMatch & { closed: BulkClosedCard };

interface MergePair {
  survivor: { id: number; name: string; lastname: string; email: string | null; phone: string | null };
  duplicateId: number;
}

/**
 * Druga linia wiersza: po niej rekruter odróżnia imienników (13.10.2026).
 * Pełny numer, jak w kolumnie „Telefon” listy Kandydaci; brak danych jest
 * napisany wprost, żeby nie wyglądał na błąd ekranu.
 */
function ContactLine({
  phone,
  email,
  location,
  interpretation,
}: {
  phone: string | null | undefined;
  email: string | null | undefined;
  location: string | null;
  interpretation: SearchTextInterpretation | null | undefined;
}) {
  // Podciąg cyfr jak wyszukiwarka (`phone_digits_clause`) — także przy 6–8 cyfrach.
  const phoneHit =
    interpretation?.kind === "phone" && phoneMatchesQuery(phone, interpretation.phone);
  const emailHit =
    interpretation?.kind === "email" &&
    !!email &&
    email.toLowerCase() === interpretation.email;
  return (
    <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-foreground">
      <span className="inline-flex items-center gap-1">
        <Phone className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden />
        {phone?.trim() ? (
          <span className={cn("font-mono tabular-nums", phoneHit && "rounded-sm bg-primary/20 px-0.5")}>
            {phone.trim()}
          </span>
        ) : (
          <span className="italic text-muted-foreground">brak telefonu</span>
        )}
      </span>
      <span className="inline-flex min-w-0 items-center gap-1">
        <Mail className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden />
        {email?.trim() ? (
          <span className={cn("truncate max-w-[220px]", emailHit && "rounded-sm bg-primary/20 px-0.5")}>
            {email.trim()}
          </span>
        ) : (
          <span className="italic text-muted-foreground">brak e-maila</span>
        )}
      </span>
      {location && <span className="truncate max-w-[140px]">· {location}</span>}
    </div>
  );
}

/**
 * „ostatnio 03.2026: Odrzucony · Rekrutacja” albo „jeszcze w żadnej rekrutacji”.
 * Data i wynik na początku: przy obcięciu linii odpada koniec nazwy rekrutacji.
 */
function historyText(c: CandidateSearchItem): string | null {
  // `undefined` = serwer nie policzył (bez kontekstu rekrutacji) — nic nie mówimy.
  if (c.last_recruitment === undefined) return null;
  if (c.last_recruitment === null) {
    const added = monthLabel(c.created_at);
    return added ? `jeszcze w żadnej rekrutacji, dodany ${added}` : "jeszcze w żadnej rekrutacji";
  }
  const { job_id, job_title, job_client_reference, stage_label, moved_on } = c.last_recruitment;
  const month = monthLabel(moved_on);
  // Nazwa jak w nagłówku rekrutacji: numer u klienta i tytuł dla rekrutera.
  const name = jobNameText({ id: job_id, title: job_title, client_reference: job_client_reference });
  return `ostatnio${month ? ` ${month}` : ""}: ${stage_label} · ${name}`;
}

export function AddCandidatesQuickModal({ open, onClose, jobId, jobTitle }: Props) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [addError, setAddError] = useState<string | null>(null);
  // Zaznaczenie przeżywa zmianę frazy, a wyniki nie — osoby ze znacznikiem
  // zapamiętujemy, żeby ramka nad stopką znała je także po nowym wyszukaniu.
  const [seenEmployed, setSeenEmployed] = useState<Map<number, EmployedPerson>>(new Map());
  const debouncedQuery = useDebouncedValue(query.trim(), 300);
  const [restoringId, setRestoringId] = useState<number | null>(null);
  const [mergePair, setMergePair] = useState<MergePair | null>(null);
  const currentUser = useAuthStore((s) => s.user);
  const canOpenProfile = useCapability("nav.candidates");
  const canMerge = useCapability("candidate.write") && canMergeCandidates(currentUser);
  const move = usePipelineMoveCore({ jobId });

  useEffect(() => {
    if (!open) {
      setQuery("");
      setSelected(new Set());
      setAddError(null);
      setSeenEmployed(new Map());
      setMergePair(null);
    }
  }, [open]);

  const { data, isFetching, isError, isSuccess } = useQuery({
    queryKey: ["add-candidates-quick", jobId, debouncedQuery],
    queryFn: () =>
      candidateSearchApi.search({
        q: debouncedQuery || undefined,
        exclude_in_job_id: jobId,
        sort: debouncedQuery ? "relevance" : "recent",
        page: 1,
        page_size: 25,
        // Runda 2: bez tego pola szybkie dodawanie NIGDY nie dotykało wektorów
        // (backendowy default to "boolean"). Bramka i tak wymaga q, więc
        // przegląd bez frazy zostaje po staremu.
        search_mode: "hybrid",
        // Nazwisko, e-mail albo telefon szukamy DOSŁOWNIE (reguła `text_mode=auto`
        // wspólnej semantyki v2, `candidate_search_predicates.interpret_text`).
        // Bez tego wpisane nazwisko szło po wektorach i obok właściwej osoby
        // wracało ~200 niezwiązanych (test na produkcji 23.09.2026).
        semantics_version: 2,
        text_mode: "auto",
      }),
    enabled: open,
    staleTime: 30_000,
  });

  const items: CandidateSearchItem[] = useMemo(() => data?.items ?? [], [data]);
  const inJob: InJobMatch[] = useMemo(() => data?.in_job_matches ?? [], [data]);
  const total = data?.total ?? 0;
  const interpretation = data?.meta?.interpretation;
  const kindLine = searchKindLine(interpretation);
  const homonyms = useMemo(() => largestHomonymGroup([...items, ...inJob]), [items, inJob]);
  const phoneRefs = useMemo(() => samePhoneRefs(items, inJob), [items, inJob]);

  useEffect(() => {
    setSeenEmployed((prev) => {
      let next = prev;
      for (const c of items) {
        if (!c.employment_marker || prev.has(c.id)) continue;
        if (next === prev) next = new Map(prev);
        next.set(c.id, {
          id: c.id,
          name: `${c.name} ${c.lastname}`.trim() || `Kandydat #${c.id}`,
          marker: c.employment_marker,
        });
      }
      return next;
    });
  }, [items]);
  const employedSelected = useMemo(
    () =>
      Array.from(selected)
        .map((id) => seenEmployed.get(id))
        .filter((person): person is EmployedPerson => person !== undefined),
    [selected, seenEmployed],
  );

  const selectedCount = selected.size;
  // Weto hiring managera (`assignment_allowed: false`) blokuje dodanie — taki
  // wiersz jest widoczny z powodem, ale nie da się go zaznaczyć. Konflikt
  // z klientem (czarna lista klienta / NDA / konkurent) od 17.09.2026 jest
  // tylko ostrzeżeniem i zaznaczyć go można.
  const selectableItems = useMemo(
    () => items.filter((c) => c.eligibility?.assignment_allowed !== false),
    [items],
  );
  const allOnPageSelected = useMemo(
    () =>
      selectableItems.length > 0 &&
      selectableItems.every((c) => selected.has(c.id)),
    [selectableItems, selected],
  );

  const toggle = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAllOnPage = () => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (allOnPageSelected) {
        for (const c of selectableItems) next.delete(c.id);
      } else {
        for (const c of selectableItems) next.add(c.id);
      }
      return next;
    });
  };

  const addMutation = useMutation({
    mutationFn: () => {
      setAddError(null);
      return proposalsBulkApi.add(jobId, {
        candidate_ids: Array.from(selected),
        source: "quick_add",
      });
    },
    onSuccess: (result: BulkProposalsResponse) => {
      queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
      queryClient.invalidateQueries({ queryKey: ["job", String(jobId)] });
      queryClient.invalidateQueries({
        queryKey: ["add-candidates-quick", jobId],
      });
      const skippedSummary =
        result.total_skipped > 0
          ? ` (pominięto ${result.total_skipped})`
          : "";
      if (result.total_added > 0) {
        showSuccess(
          `Dodano ${result.total_added} ${result.total_added === 1 ? "kandydata" : "kandydatów"} do pipeline${skippedSummary}`,
        );
      } else if (result.total_skipped > 0) {
        showError(
          `Nie dodano nikogo — wszyscy zostali pominięci (${result.total_skipped})`,
        );
      }
      setSelected(new Set());
      if (result.total_added > 0) onClose();
    },
    onError: (error: unknown) => {
      const message = assignErrorMessage(error);
      setAddError(message);
      showError(message);
    },
  });

  // Przywrócenie zamkniętej karty to ruch karty, nie drugie dodanie — ta sama
  // ścieżka co okno „Dodaj do rekrutacji” (anulowanie maila odmowy, ostrzeżenia).
  const restore = async (person: ClosedInJob) => {
    setRestoringId(person.id);
    let restored = false;
    try {
      const outcome = await move.send(restoreMovePayload(person.id, jobId, person.closed), {
        candidateName: person.closed.candidate_name,
        eligibilitySubject: person.closed.candidate_name,
        fallbackMessage: "Nie udało się przywrócić karty.",
      });
      restored = outcome.ok;
    } finally {
      setRestoringId(null);
    }
    if (!restored) return;
    void queryClient.invalidateQueries({ queryKey: ["add-candidates-quick", jobId] });
    void queryClient.invalidateQueries({ queryKey: ["pipeline-scores"] });
    void queryClient.invalidateQueries({ queryKey: ["my-next-steps"] });
  };

  // W trakcie „Przywróć” okno zostaje: ruch karty może jeszcze pokazać swoje
  // okna (ostrzeżenia, konflikt wersji), a po zamknięciu nie miałby ich gdzie
  // pokazać i przycisk zostawałby zablokowany (audyt 13.10.2026). Jak
  // `close` w `AddToRecruitmentDialog`.
  const close = () => {
    if (restoringId !== null) return;
    onClose();
  };

  const personById = (id: number) =>
    items.find((c) => c.id === id) ?? inJob.find((p) => p.id === id) ?? null;

  const openMerge = (duplicateId: number, ref: SamePhoneRef) => {
    const survivor = personById(ref.id);
    if (!survivor) return;
    setMergePair({
      survivor: {
        id: survivor.id,
        name: survivor.name,
        lastname: survivor.lastname,
        email: survivor.email ?? null,
        phone: survivor.phone ?? null,
      },
      duplicateId,
    });
  };

  const statusText = (() => {
    if (!debouncedQuery) {
      return `Najnowsi kandydaci — wpisz frazę, by przefiltrować (${total} łącznie)`;
    }
    const found = kindLine
      ? `${kindLine} · ${countPl(total, "wynik", "wyniki", "wyników")}`
      : `Znaleziono ${countPl(total, "wynik", "wyniki", "wyników")}`;
    return inJob.length > 0
      ? `${found} · ${countPl(inJob.length, "osoba jest", "osoby są", "osób jest")} już w tej rekrutacji (niżej)`
      : `${found} (już dodani do tej rekrutacji są ukryci)`;
  })();

  if (!open) return null;

  // Rama na `Dialog` (Radix): Escape i klik w tło zamykają, fokus zostaje
  // w oknie, a czytnik ekranu dostaje `role="dialog"` z tytułem. Logika
  // wyszukiwania i dodawania bez zmian.
  return (
    <Dialog open onOpenChange={(next) => { if (!next) close(); }}>
      <DialogContent
        size="lg"
        hideClose
        className="rounded-2xl shadow-xl max-h-[88dvh]"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div className="flex items-center gap-2 min-w-0">
            <UserPlus className="w-5 h-5 text-primary shrink-0" />
            <div className="min-w-0">
              <DialogTitle className="text-lg font-bold text-foreground truncate">
                Dodaj kandydatów do pipeline
              </DialogTitle>
              <p className="text-xs text-muted-foreground truncate">
                Rekrutacja: {jobTitle}
              </p>
            </div>
          </div>
          <button
            onClick={close}
            disabled={restoringId !== null}
            className="text-muted-foreground hover:text-foreground transition-colors disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="Zamknij"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Search input */}
        <div className="px-6 py-3 border-b border-border">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <input
              autoFocus
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Imię i nazwisko, telefon albo e-mail…"
              className="w-full pl-9 pr-9 py-2.5 border border-border rounded-lg text-sm bg-card focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
            />
            {isFetching && (
              <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground animate-spin" />
            )}
          </div>
          <div className="flex items-center justify-between mt-2 text-xs text-muted-foreground">
            <span>{statusText}</span>
            {selectableItems.length > 0 && (
              <button
                onClick={toggleAllOnPage}
                className="text-primary hover:underline font-medium"
              >
                {allOnPageSelected ? "Odznacz wszystkich" : "Zaznacz wszystkich"}
              </button>
            )}
          </div>
        </div>

        {/* Results */}
        <div className="flex-1 overflow-y-auto px-3 py-2">
          {addError && (
            <div
              role="alert"
              className="flex items-start gap-2 px-4 py-3 m-3 bg-destructive/10 border border-destructive/20 rounded-lg text-sm text-destructive"
            >
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
              <div>
                <p className="font-medium">Nie można dodać kandydatów</p>
                <p className="mt-0.5 text-xs">{addError}</p>
              </div>
            </div>
          )}

          {isError && (
            <div className="flex items-center gap-2 px-4 py-3 m-3 bg-destructive/10 border border-destructive/20 rounded-lg text-sm text-destructive">
              <AlertCircle className="w-4 h-4 shrink-0" />
              Błąd wyszukiwania. Spróbuj ponownie.
            </div>
          )}

          {isSuccess && items.length === 0 && !isFetching && (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground gap-2">
              <Search className="w-10 h-10 opacity-30" />
              <p className="text-sm">
                {inJob.length > 0
                  ? "Wszystkie pasujące osoby są już w tej rekrutacji"
                  : debouncedQuery
                    ? "Brak wyników dla tej frazy"
                    : "Wpisz imię lub nazwisko kandydata"}
              </p>
            </div>
          )}

          {homonyms && (
            <div
              role="status"
              className="mx-1 mb-2 flex items-start gap-2 rounded-lg border border-info/20 bg-info-muted px-3 py-2 text-xs text-info-muted-foreground"
              data-testid="add-candidates-homonyms"
            >
              <Users className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              <span>
                <span className="font-semibold">
                  {countPl(homonyms.count, "osoba", "osoby", "osób")} o imieniu i nazwisku{" "}
                  {homonyms.label}.
                </span>{" "}
                Porównaj telefon i e-mail, zanim zaznaczysz.
              </span>
            </div>
          )}

          {items.map((c) => {
            const isSelected = selected.has(c.id);
            const fullName = `${c.name} ${c.lastname}`.trim();
            const initials = initialsOf(c.name, c.lastname);
            const color = avatarColorFor(fullName || String(c.id));
            const candidateLocation = formatCandidateLocation(c.location);
            const elig = c.eligibility;
            const assignBlocked = elig?.assignment_allowed === false;
            const phoneRef = phoneRefs.get(c.id);
            const history = historyText(c);
            return (
              <div
                key={c.id}
                className={cn(
                  "mb-1 flex items-start rounded-lg transition-colors",
                  isSelected ? "bg-primary/10 ring-1 ring-primary/30" : "hover:bg-muted",
                )}
              >
                {/* Przycisk zaznacza; „Profil” i „Scal…” stoją obok, bo
                    w przycisku nie wolno zagnieżdżać linków ani przycisków. */}
                <button
                  type="button"
                  onClick={() => toggle(c.id)}
                  disabled={assignBlocked}
                  title={assignBlocked ? elig?.reason : undefined}
                  className="flex min-w-0 flex-1 items-start gap-3 rounded-lg px-3 py-2.5 text-left disabled:cursor-not-allowed disabled:opacity-60"
                  data-testid={`add-candidate-row-${c.id}`}
                >
                  <div
                    className={cn(
                      "mt-2 w-5 h-5 rounded border flex items-center justify-center shrink-0 transition-colors",
                      isSelected
                        ? "bg-primary border-primary"
                        : "border-border bg-card",
                    )}
                  >
                    {isSelected && <Check className="w-3.5 h-3.5 text-white" />}
                  </div>
                  <div
                    className={cn(
                      "w-9 h-9 rounded-full flex items-center justify-center text-white font-semibold text-xs shrink-0",
                      color,
                    )}
                  >
                    {initials}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium text-sm text-foreground truncate">
                        {fullName || "—"}
                      </span>
                      {c.is_champion && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-warning-muted text-warning-muted-foreground font-medium">
                          Champion
                        </span>
                      )}
                      {c.employment_marker && <EmploymentPill marker={c.employment_marker} />}
                      {elig && !markerCoversEligibility(c.employment_marker, elig.reason_code) && (
                        <span
                          className={cn(
                            "inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                            eligibilityBadgeClass(elig),
                          )}
                          data-testid={`add-candidate-eligibility-${c.id}`}
                        >
                          <AlertCircle className="h-3 w-3 shrink-0" />
                          {elig.reason}
                        </span>
                      )}
                      {phoneRef && (
                        <span
                          className="rounded-full bg-warning-muted px-1.5 py-0.5 text-[10px] font-medium text-warning-muted-foreground"
                          data-testid={`add-candidate-same-phone-${c.id}`}
                        >
                          {samePhoneLabel(phoneRef)}
                        </span>
                      )}
                    </div>
                    <ContactLine
                      phone={c.phone}
                      email={c.email}
                      location={candidateLocation}
                      interpretation={interpretation}
                    />
                    {/* Jedna linia: przy trzech liniach w wierszu okno 1280 × 720
                        mieści jeszcze cztery–pięć osób bez przewijania. */}
                    <div className="mt-0.5 flex min-w-0 items-center gap-x-2 text-xs text-muted-foreground">
                      {c.competence_category && (
                        <span className="max-w-[130px] shrink-0 truncate">
                          <CompetenceCategoryName slug={c.competence_category} />
                        </span>
                      )}
                      {history && (
                        <span className="min-w-0 truncate" title={history}>
                          {c.competence_category ? "· " : ""}
                          {history}
                        </span>
                      )}
                      {c.source && (
                        <span className="max-w-[100px] shrink-0 truncate">· {c.source}</span>
                      )}
                    </div>
                  </div>
                </button>
                <div className="flex shrink-0 flex-col items-end gap-1.5 py-2.5 pr-3">
                  {canOpenProfile && (
                    <a
                      href={`/candidates/${c.id}?from=job&jobId=${jobId}`}
                      target="_blank"
                      rel="noopener"
                      className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                      aria-label={`Profil: ${fullName || `kandydat #${c.id}`} (nowa karta)`}
                    >
                      Profil
                      <ExternalLink className="h-3 w-3" aria-hidden />
                    </a>
                  )}
                  {canMerge && phoneRef && (
                    <button
                      type="button"
                      onClick={() => openMerge(c.id, phoneRef)}
                      className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                      data-testid={`add-candidate-merge-${c.id}`}
                    >
                      <GitMerge className="h-3 w-3" aria-hidden />
                      Scal…
                    </button>
                  )}
                </div>
              </div>
            );
          })}

          {inJob.length > 0 && (
            <section
              aria-label="Już w tej rekrutacji"
              className="mt-2 border-t border-border pt-2"
              data-testid="add-candidates-in-job"
            >
              <p className="px-3 pb-1 text-xs font-semibold text-muted-foreground">
                Już w tej rekrutacji ({inJob.length})
              </p>
              {inJob.map((person) => {
                const fullName = `${person.name} ${person.lastname}`.trim();
                const closed = person.closed ?? null;
                return (
                  <div
                    key={person.id}
                    className="mb-1 flex items-start gap-3 rounded-lg px-3 py-2.5"
                    data-testid={`add-candidate-in-job-${person.id}`}
                  >
                    <div className="mt-2 h-5 w-5 shrink-0 rounded border border-dashed border-border" aria-hidden />
                    <div
                      className={cn(
                        "w-9 h-9 rounded-full flex items-center justify-center text-white font-semibold text-xs shrink-0 opacity-80",
                        avatarColorFor(fullName || String(person.id)),
                      )}
                    >
                      {initialsOf(person.name, person.lastname)}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="truncate text-sm font-medium text-foreground">
                          {fullName || "—"}
                        </span>
                        <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                          {person.card_label}
                        </span>
                      </div>
                      <ContactLine
                        phone={person.phone}
                        email={person.email}
                        location={formatCandidateLocation(person.location)}
                        interpretation={interpretation}
                      />
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1.5">
                      {canOpenProfile && (
                        <a
                          href={`/candidates/${person.id}?from=job&jobId=${jobId}`}
                          target="_blank"
                          rel="noopener"
                          className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                          aria-label={`Profil: ${fullName || `kandydat #${person.id}`} (nowa karta)`}
                        >
                          Profil
                          <ExternalLink className="h-3 w-3" aria-hidden />
                        </a>
                      )}
                      {closed && (
                        <button
                          type="button"
                          onClick={() => void restore({ ...person, closed })}
                          disabled={restoringId !== null}
                          className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border border-border bg-card px-2.5 py-1 text-xs font-medium text-foreground hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60"
                          data-testid={`add-candidate-restore-${person.id}`}
                        >
                          {restoringId === person.id ? (
                            <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
                          ) : (
                            <RotateCcw className="h-3 w-3" aria-hidden />
                          )}
                          {restoreLabel(closed)}
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </section>
          )}
        </div>

        {/* Zaznaczona osoba u nas pracuje: informacja, nie blokada. */}
        <EmployedPeopleNotice
          people={employedSelected}
          total={selectedCount}
          hint={ADD_ANYWAY_HINT}
          className="mx-3 mb-3"
        />

        {/* Footer */}
        <div className="flex items-center justify-between gap-3 px-6 py-4 border-t border-border bg-muted/30 rounded-b-2xl">
          <span className="text-sm text-muted-foreground">
            {selectedCount > 0
              ? `Zaznaczono ${selectedCount} ${selectedCount === 1 ? "kandydata" : "kandydatów"}`
              : "Wybierz kandydatów do dodania"}
          </span>
          <div className="flex gap-2">
            <button
              onClick={close}
              disabled={restoringId !== null}
              className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors disabled:cursor-not-allowed disabled:opacity-50"
            >
              Anuluj
            </button>
            <button
              onClick={() => addMutation.mutate()}
              disabled={selectedCount === 0 || addMutation.isPending}
              className="flex items-center gap-1.5 px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              data-testid="add-candidates-confirm"
            >
              {addMutation.isPending ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Dodaję...
                </>
              ) : (
                <>
                  <UserPlus className="w-4 h-4" />
                  Dodaj do pipeline
                  {selectedCount > 0 && ` (${selectedCount})`}
                </>
              )}
            </button>
          </div>
        </div>
        {move.dialogs}
        {mergePair && (
          <CandidateMergeDialog
            key={`${mergePair.survivor.id}-${mergePair.duplicateId}`}
            open
            onOpenChange={(next) => {
              if (next) return;
              setMergePair(null);
              void queryClient.invalidateQueries({ queryKey: ["add-candidates-quick", jobId] });
            }}
            candidate={mergePair.survivor}
            initialDuplicateId={mergePair.duplicateId}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
