"use client";

/**
 * Talent Radar — wklejasz treść requestu, dostajesz ranking bazy kandydatów.
 *
 * Cztery decyzje, które widać w kodzie i które nie są kosmetyczne:
 *
 * 1. Rekrutacja jest OBOWIĄZKOWA i wybrana przed wyszukiwaniem. Jej klient
 *    zasila filtr dopuszczalności (blacklista, NDA, konflikty i weto), a jej id
 *    jest jednoznacznym celem przycisku „Przypisz do rekrutacji”.
 *
 * 2. Szukanie idzie na PRZYCISK (`useMutation`), nie na wpisywanie. Zapytanie
 *    liczy embedding i przemiela pulę do tysiąca kandydatów — debounce na
 *    każdym naciśnięciu klawisza zamieniłby pisanie opisu roli w kilkadziesiąt
 *    takich przebiegów.
 *
 * 3. `meta.degraded` renderuje się jako AWARIA, nigdy jako pusty stan. Gdy
 *    Qdrant albo Voyage nie odpowiada, backend zwraca zero wyników z tą flagą;
 *    pokazanie wtedy „brak dopasowań" byłoby kłamstwem w najgorszą stronę —
 *    rekruter uznałby, że w bazie nie ma nikogo takiego.
 *
 * 4. To samo dotyczy błędu HTTP, który wcześniej lądował WYŁĄCZNIE w toaście:
 *    po jego zniknięciu zostawał ekran startowy „Zacznij od wklejenia
 *    requestu", czyli zdanie o tym, że rekruter nic nie zrobił. Błąd jedzie
 *    więc do `TalentRadarResults` i zostaje na ekranie do następnej próby.
 */

import { useEffect, useMemo, useState } from "react";
import { Radar } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { PageHeader } from "@/components/ds";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { TalentRadarRecruitmentPicker } from "@/components/talent-radar/TalentRadarRecruitmentPicker";
import { useToast } from "@/components/Toast";
import { useCapability } from "@/hooks/useCapability";
import { extractErrorMsg, recommendationsApi } from "@/lib/api";
import { assignErrorMessage } from "@/lib/assign-error";
import type { TalentRadarRecruitmentRef } from "@/lib/talent-radar-recruitment";
import {
  talentRadarApi,
  type ChampionParseSummary,
  type TalentRadarSearchResponse,
} from "@/lib/talent-radar-api";
import {
  loadTalentRadarSession,
  saveTalentRadarSession,
} from "@/lib/talent-radar-session";
import { TalentRadarResults } from "@/components/talent-radar/TalentRadarResults";

/** Poniżej tego progu opis roli nie niesie sygnału wartego embeddingu. */
const MIN_QUERY_LENGTH = 30;

export function TalentRadarWorkspace() {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  // Radar jest dla KAŻDEJ roli, ale pełny profil kandydata pozostaje za
  // bramkami modułu kandydatów — rola bez tej capability nie dostaje
  // martwego przycisku „Otwórz profil" (klik kończyłby się 403).
  const canOpenProfile = useCapability("nav.candidates");
  const canAssignCandidate = useCapability("candidate.assign_to_job");
  const [recruitment, setRecruitment] =
    useState<TalentRadarRecruitmentRef | null>(null);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [response, setResponse] = useState<TalentRadarSearchResponse | null>(
    null,
  );
  // Dealbreaker-switche: budżet podaje rekruter wprost (radar nie ma oferty)
  // i SAMA jego obecność działa jako twardy sufit — bez marginesu, bez
  // osobnego uzbrajania (decyzja produktowa 19.08). Nieznana stawka/
  // preferencja kandydata przechodzi po stronie backendu.
  const [budgetMax, setBudgetMax] = useState("");
  const [excludeRemoteOnly, setExcludeRemoteOnly] = useState(false);
  // Profil Championa z pliku (docx/pdf): rekruter dostaje go jako DOKUMENT —
  // wklejanie do pola tekstowego gubi strukturę (stawka, must/nice).
  const [championProfile, setChampionProfile] = useState<Record<
    string,
    unknown
  > | null>(null);
  const [championSummary, setChampionSummary] =
    useState<ChampionParseSummary | null>(null);
  // Wymagania z profilu trzymane OSOBNO od `championProfile`: ten obiekt jest
  // przekazywany na backend verbatim jako `jobs.champion_profile` i wymagań
  // NIE niesie (`build_champion_dict` ich nie kopiuje). Bez tego stanu listy
  // z `parse-champion` przepadają po jednym renderze i ranking wraca do
  // wywodzenia wymagań z prozy — czyli tu urywał się łańcuch.
  const [championSkills, setChampionSkills] = useState<{
    must: string[];
    nice: string[];
  } | null>(null);
  const [parsingChampion, setParsingChampion] = useState(false);
  const [assignedCandidateIds, setAssignedCandidateIds] = useState<Set<number>>(
    () => new Set(),
  );

  // ── Snapshot roboczy (sessionStorage) ────────────────────────────────
  // „Otwórz profil" nawiguje w tej samej karcie, a ta strona przy powrocie
  // montuje się OD ZERA — bez snapshotu rekruter wracał na pusty formularz
  // i układał wyszukiwanie od nowa. Odczyt idzie w efekcie PO montażu,
  // nie w inicjalizatorach `useState`: strona jest prerenderowana
  // server-side, gdzie sessionStorage nie istnieje, więc inicjalizator
  // dałby hydration mismatch (serwer: pusto, klient: dane).
  //
  // `hydrated` jest STANEM, nie refem — efekt zapisu czyta go z closure
  // bieżącego renderu, więc pierwszy przebieg (jeszcze z pustym stanem)
  // gwarantowanie nie nadpisze snapshotu, zanim restore się przerenderuje.
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    const saved = loadTalentRadarSession();
    if (saved) {
      setRecruitment(saved.recruitment);
      setTitle(saved.title);
      setText(saved.text);
      setBudgetMax(saved.budgetMax);
      setExcludeRemoteOnly(saved.excludeRemoteOnly);
      setChampionProfile(saved.championProfile);
      setChampionSummary(saved.championSummary);
      setResponse(saved.response);
    }
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    saveTalentRadarSession({
      recruitment,
      title,
      text,
      budgetMax,
      excludeRemoteOnly,
      championProfile,
      championSummary,
      response,
    });
  }, [
    hydrated,
    recruitment,
    title,
    text,
    budgetMax,
    excludeRemoteOnly,
    championProfile,
    championSummary,
    response,
  ]);

  const search = useMutation({
    mutationFn: () =>
      talentRadarApi.search({
        client_id: recruitment!.clientId,
        text: championProfile ? undefined : text.trim() || undefined,
        champion_profile: championProfile ?? undefined,
        // Przy profilu nazwa roli pochodzi Z NIEGO (championSummary.role_name),
        // nie z ręcznego pola — nie ma po co jej dublować.
        title: championProfile
          ? championSummary?.role_name || undefined
          : title.trim() || undefined,
        top_k: 20,
        // Puste listy pomijamy (`undefined`), żeby nie wysyłać `[]` — dla
        // backendu „brak wymagań wprost" i „pusta lista" to ta sama decyzja,
        // ale krótsze ciało requestu czyta się jednoznacznie.
        must_skills: championSkills?.must.length
          ? championSkills.must
          : undefined,
        nice_skills: championSkills?.nice.length
          ? championSkills.nice
          : undefined,
        budget_hourly_max:
          Number(budgetMax) > 0 ? Number(budgetMax) : undefined,
        exclude_remote_only: excludeRemoteOnly || undefined,
      }),
    onSuccess: (data) => setResponse(data),
    onError: (error: unknown) => {
      // Toast zostaje (natychmiastowy sygnał), ale nie jest już JEDYNYM
      // śladem awarii — `search.error` renderuje się w wynikach.
      setResponse(null);
      showError(extractErrorMsg(error));
    },
  });

  const assignCandidate = useMutation({
    mutationFn: async ({
      candidateId,
      recruitmentId,
    }: {
      candidateId: number;
      recruitmentId: number;
    }) => {
      const response = await recommendationsApi.assignToJob(
        candidateId,
        recruitmentId,
      );
      return {
        candidateId,
        recruitmentId,
        status: response.data?.status as string | undefined,
      };
    },
    onSuccess: ({ candidateId, recruitmentId, status }) => {
      if (recruitment?.id === recruitmentId) {
        setAssignedCandidateIds((current) => new Set(current).add(candidateId));
      }
      showSuccess(
        status === "already_in_pipeline"
          ? "Kandydat jest już w tej rekrutacji."
          : "Kandydat przypisany do rekrutacji.",
      );
      queryClient.invalidateQueries({
        queryKey: ["kanban", recruitmentId],
      });
      queryClient.invalidateQueries({
        queryKey: ["kanban", String(recruitmentId)],
      });
    },
    onError: (error: unknown) => showError(assignErrorMessage(error)),
  });

  // Zmiana wejścia unieważnia POPRZEDNI błąd tak samo jak poprzednie wyniki:
  // komunikat „nie udało się" wiszący nad świeżo wybraną rekrutacją opisywałby
  // zapytanie, którego już nie ma.
  const clearResults = () => {
    setResponse(null);
    search.reset();
  };

  const hasProfile = championProfile !== null;
  const tooShort = text.trim().length < MIN_QUERY_LENGTH;
  const blocked = useMemo(() => {
    if (!recruitment) return "Wybierz rekrutację.";
    if (!hasProfile && tooShort)
      return `Wgraj profil Championa ALBO wklej opis roli (min. ${MIN_QUERY_LENGTH} znaków).`;
    return null;
  }, [recruitment, tooShort, hasProfile]);

  const onChampionFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null;
    // Reset inputu OD RAZU: bez tego po błędzie parsowania przeglądarka nie
    // odpali onChange przy ponownym wyborze tego samego pliku (recenzja #1204).
    e.target.value = "";
    if (!f) return;
    setParsingChampion(true);
    try {
      const res = await talentRadarApi.parseChampion(f);
      setChampionProfile(res.champion_profile);
      setChampionSummary(res.summary);
      // `?? []` mimo wymaganych pól w typie: to dane z sieci, a nie z
      // kompilatora. Starsza odpowiedź bez tych kluczy zamieniłaby klik
      // „Szukaj kandydatów" w TypeError zamiast w wyszukiwanie.
      setChampionSkills({
        must: res.must_skills ?? [],
        nice: res.nice_skills ?? [],
      });
      // Stawka z profilu = budżet klienta na kandydata — pre-fill dla
      // dealbreakera (rekruter może nadpisać/wyczyścić).
      if (res.summary.rate_value && !budgetMax) {
        setBudgetMax(String(res.summary.rate_value));
      }
      clearResults();
    } catch (error: unknown) {
      showError(extractErrorMsg(error));
    } finally {
      setParsingChampion(false);
    }
  };

  const meta = response?.meta;
  const results = response?.results ?? [];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Sourcing"
        title="Talent Radar"
        description="Wybierz rekrutację, a następnie wgraj profil Championa ALBO wklej treść requestu. Kandydatów z rankingu przypiszesz do niej jednym kliknięciem."
        density="compact"
      />

      <div className="flex flex-col gap-4 rounded-lg border border-border bg-card p-4">
        {/* Profil na SAMEJ GÓRZE: steruje resztą formularza (stawka
            wskakuje w budżet, nazwa roli idzie z profilu, treść requestu
            znika) — pola, na które wpływa, muszą stać PO nim. */}
        {hasProfile ? (
          <div className="flex flex-col gap-2">
            <Label>Profil Championa</Label>
            <div
              className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-muted px-3 py-2 text-sm"
              data-testid="tr-champion-loaded"
            >
              <span className="font-medium">
                {championSummary?.role_name || "Profil wczytany"}
              </span>
              <span className="text-muted-foreground">
                {championSummary?.must_count} must ·{" "}
                {championSummary?.nice_count} nice
                {championSummary?.rate_value
                  ? ` · ${championSummary.rate_value} PLN/h`
                  : ""}
                {championSummary?.location
                  ? ` · ${championSummary.location}`
                  : ""}
              </span>
              <button
                type="button"
                className="ml-auto text-xs text-muted-foreground underline hover:text-foreground"
                onClick={() => {
                  setChampionProfile(null);
                  setChampionSummary(null);
                  setChampionSkills(null);
                  clearResults();
                }}
              >
                Usuń
              </button>
            </div>
            <p className="text-xs text-muted-foreground">
              Profil niesie wymagania, stawkę, nazwę roli i kontekst — treść
              requestu jest już niepotrzebna.
            </p>
          </div>
        ) : (
          // Albo-albo WIDAĆ z układu: plik i treść stoją OBOK SIEBIE,
          // rozdzielone pastylką „ALBO" — nie trzeba tego wyczytywać z opisu.
          <div className="grid gap-3 md:grid-cols-[1fr_auto_1fr] md:items-stretch">
            <div className="flex flex-col gap-2 rounded-md border border-dashed border-border p-3">
              <Label htmlFor="tr-champion-file">Profil Championa (plik)</Label>
              <input
                id="tr-champion-file"
                type="file"
                accept=".docx,.pdf"
                disabled={parsingChampion}
                onChange={onChampionFile}
                className="text-sm file:mr-3 file:rounded-md file:border file:border-border file:bg-background file:px-3 file:py-1.5 file:text-sm hover:file:bg-accent"
              />
              <p className="text-xs text-muted-foreground">
                {parsingChampion
                  ? "Parsuję profil…"
                  : "Docx/pdf od zespołu — odczytamy wymagania, stawkę i nazwę roli."}
              </p>
            </div>
            <div className="flex items-center justify-center">
              <span className="rounded-full border border-border bg-muted px-3 py-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                albo
              </span>
            </div>
            <div className="flex flex-col gap-2 rounded-md border border-dashed border-border p-3">
              <Label htmlFor="tr-text">Treść requestu</Label>
              <Textarea
                id="tr-text"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Wklej maila od klienta, opis stanowiska albo listę wymagań — jak leci."
                rows={6}
                maxLength={20_000}
                className="flex-1"
              />
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span className={blocked ? "text-destructive" : ""}>
                  {blocked ?? "Gotowe do wyszukania."}
                </span>
                <span>{text.length.toLocaleString("pl-PL")} / 20 000</span>
              </div>
            </div>
          </div>
        )}

        <div className="grid gap-4 md:grid-cols-2">
          <div className="flex flex-col gap-2">
            <Label htmlFor="tr-recruitment">
              Rekrutacja <span className="text-destructive">*</span>
            </Label>
            <TalentRadarRecruitmentPicker
              value={recruitment}
              onChange={(picked) => {
                setRecruitment(picked);
                setAssignedCandidateIds(new Set());
                // Rekrutacja wyznacza jednocześnie klienta filtra i cel akcji.
                // Po jej zmianie poprzednie wyniki oraz lokalne stany
                // „Przypisano" nie mogą zostać pod nowym kontekstem.
                clearResults();
              }}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="tr-budget">Budżet PLN/h</Label>
            <div className="flex items-center gap-2">
              <Input
                id="tr-budget"
                type="number"
                min={1}
                max={2000}
                value={budgetMax}
                onChange={(e) => setBudgetMax(e.target.value)}
                placeholder="np. 150"
                className="w-28"
              />
              <label className="flex items-center gap-1.5 text-sm">
                <input
                  type="checkbox"
                  checked={excludeRemoteOnly}
                  onChange={(e) => setExcludeRemoteOnly(e.target.checked)}
                  data-testid="tr-exclude-remote-only"
                />
                praca z biura — ukryj „wyłącznie zdalnie”
              </label>
            </div>
            <p className="text-xs text-muted-foreground">
              {championSummary?.rate_value
                ? `Stawka ${championSummary.rate_value} PLN/h wzięta z profilu Championa — wpisz własną, żeby ją nadpisać, albo wyczyść pole, żeby wyłączyć sufit.`
                : "Wpisana stawka to twardy sufit: nie pokażemy osób ze ZNANĄ stawką powyżej niej. Brak danych zawsze przechodzi; ukrytych policzymy w wynikach."}
            </p>
          </div>
          {!hasProfile && (
            <div className="flex flex-col gap-2">
              <Label htmlFor="tr-title">Nazwa roli</Label>
              <Input
                id="tr-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="np. Senior Python Developer"
                maxLength={300}
              />
              <p className="text-xs text-muted-foreground">
                Opcjonalna — wzmacnia dopasowanie. Przy wgranym profilu nazwę
                bierzemy z niego.
              </p>
            </div>
          )}
        </div>

        {hasProfile && blocked && (
          <p className="text-xs text-destructive">{blocked}</p>
        )}

        <div className="flex justify-end">
          <Button
            onClick={() => search.mutate()}
            disabled={blocked !== null || search.isPending}
          >
            <Radar className="mr-2 h-4 w-4" />
            {search.isPending ? "Szukam…" : "Szukaj kandydatów"}
          </Button>
        </div>
      </div>

      <TalentRadarResults
        meta={meta ?? null}
        results={results}
        pending={search.isPending}
        error={search.isError ? search.error : null}
        onRetry={() => search.mutate()}
        canOpenProfile={canOpenProfile}
        canAssign={canAssignCandidate && recruitment !== null}
        targetRecruitmentTitle={recruitment?.title}
        onAssign={(candidateId) => {
          if (!recruitment) return;
          assignCandidate.mutate({
            candidateId,
            recruitmentId: recruitment.id,
          });
        }}
        assigningCandidateId={
          assignCandidate.isPending
            ? (assignCandidate.variables?.candidateId ?? null)
            : null
        }
        assignedCandidateIds={assignedCandidateIds}
      />
    </div>
  );
}
