"use client";

/** Talent Radar uses the shared, durable full-population search.
 * A click starts a scan; subsequent reads poll and paginate that same run.
 * Only the request form and actor-scoped run ID survive profile navigation.
 */

import { useEffect, useMemo, useState } from "react";
import { Radar } from "lucide-react";
import { useAuthStore } from "@/store/auth";
import { hasSectionAccess } from "@/lib/section-access";
import { SavedRequestSearch } from "./SavedRequestSearch";
import { useFullCandidateSearch } from "@/hooks/useFullCandidateSearch";

import { PageHeader } from "@/components/ds";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import {
  TalentRadarClientPicker,
  type ClientRef,
} from "@/components/talent-radar/TalentRadarClientPicker";
import { useToast } from "@/components/Toast";
import { useCapability } from "@/hooks/useCapability";
import { extractErrorMsg } from "@/lib/api";
import {
  talentRadarApi,
  type ChampionParseSummary,
} from "@/lib/talent-radar-api";
import {
  loadTalentRadarSession,
  saveTalentRadarSession,
} from "@/lib/talent-radar-session";
import { FullCandidateSearchResults } from "@/components/talent-radar/FullCandidateSearchResults";

/** Poniżej tego progu opis roli nie niesie sygnału wartego embeddingu. */
const MIN_QUERY_LENGTH = 30;

export function TalentRadarWorkspace() {
  const user = useAuthStore(s => s.user);
  const canReadJobs = hasSectionAccess(user, "pipeline", "read");
  const [mode, setMode] = useState<"adhoc" | "saved">("adhoc");
  useEffect(() => {
    if (!user?.id) return;
    try { if (sessionStorage.getItem(`nexus-radar-mode:${user.id}`) === "saved") setMode("saved"); } catch {}
  }, [user?.id]);
  const choose = (value: "adhoc" | "saved") => {
    setMode(value);
    if (user?.id) { try { sessionStorage.setItem(`nexus-radar-mode:${user.id}`, value); } catch {} }
  };
  return <div className="space-y-4">
    {canReadJobs && <div className="flex gap-2" aria-label="Źródło requestu">
      <Button variant={mode === "adhoc" ? "primary" : "outline"} onClick={() => choose("adhoc")}>Nowy request</Button>
      <Button variant={mode === "saved" ? "primary" : "outline"} onClick={() => choose("saved")}>Zapisana rekrutacja</Button>
    </div>}
    {mode === "saved" && canReadJobs ? <SavedRequestSearch /> : <AdHocTalentRadarWorkspace />}
  </div>;
}

function AdHocTalentRadarWorkspace() {
  const { showError } = useToast();
  // Radar jest dla KAŻDEJ roli, ale pełny profil kandydata pozostaje za
  // bramkami modułu kandydatów — rola bez tej capability nie dostaje
  // martwego przycisku „Otwórz profil" (klik kończyłby się 403).
  const canOpenProfile = useCapability("nav.candidates");
  const [client, setClient] = useState<ClientRef | null>(null);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  // Lokalizacja: API przyjmowało ją od początku, interfejs nie miał pola.
  // W trybie tekstowym KAŻDY kandydat dostawał przez to „lokalizacja nieznana"
  // (3,2 z 5 punktów) — zmierzone: z podaną lokalizacją pierwszy wynik zmienia
  // się na osobę z właściwego miasta.
  const [location, setLocation] = useState("");
  const actorId = useAuthStore(s => s.user?.id);
  const fullSearch = useFullCandidateSearch({ storageKey: actorId ? `nexus-full-radar:${actorId}` : undefined });
  useEffect(() => { if (fullSearch.error) showError(extractErrorMsg(fullSearch.error)); }, [fullSearch.error, showError]);
  // Dealbreaker-switche: budżet podaje rekruter wprost (radar nie ma oferty)
  // i SAMA jego obecność działa jako twardy sufit — bez marginesu, bez
  // osobnego uzbrajania (decyzja produktowa 19.08). Nieznana stawka/
  // preferencja kandydata przechodzi po stronie backendu.
  const [budgetMax, setBudgetMax] = useState("");
  const [excludeRemoteOnly, setExcludeRemoteOnly] = useState(false);
  // Rubryki 0278: dni w biurze / tydzień i miasto biura, podane WPROST przez
  // rekrutera (radar nie ma kolumn oferty ani profilu Championa do fallbacku
  // dla tych dwóch pól). Puste pole = „nie wiem" i nie uzbraja żadnego
  // dealbreakera; `0` jest LEGALNĄ, ZNANĄ wartością („wyłącznie zdalnie"), więc
  // trzymamy je jako string i sprawdzamy pustkę wprost, nie `> 0` jak budżet.
  const [onsiteDaysPerWeek, setOnsiteDaysPerWeek] = useState("");
  const [officeLocation, setOfficeLocation] = useState("");
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
  const [requirementsPreview, setRequirementsPreview] = useState<{
    source: string; must: string; nice: string; excluded: string[]; uncertain: string[];
  } | null>(null);
  const [interpreting, setInterpreting] = useState(false);
  const requirementSource = JSON.stringify([text, title, championProfile]);
  const previewCurrent = requirementsPreview?.source === requirementSource;
  const splitSkills = (value: string) => value.split(/[,;\n]/).map(s => s.trim()).filter(Boolean);
  const previewRequirements = async () => {
    if (!client) return;
    setInterpreting(true);
    try {
      const parsed = await talentRadarApi.interpret({
        client_id: client.id, text: championProfile ? undefined : text,
        title: championProfile ? championSummary?.role_name ?? undefined : title,
        champion_profile: championProfile ?? undefined,
        must_skills: championSkills?.must, nice_skills: championSkills?.nice,
      });
      setRequirementsPreview({ source: requirementSource, must: parsed.must.join(", "),
        nice: parsed.nice.join(", "), excluded: parsed.excluded, uncertain: parsed.uncertain });
      fullSearch.clear();
    } catch (error) { showError(extractErrorMsg(error)); }
    finally { setInterpreting(false); }
  };


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
      setClient(saved.client);
      setTitle(saved.title);
      setText(saved.text);
      setLocation(saved.location ?? "");
      setChampionSkills(saved.championSkills ?? null);
      setRequirementsPreview(saved.requirementsPreview ?? null);
      setBudgetMax(saved.budgetMax);
      setExcludeRemoteOnly(saved.excludeRemoteOnly);
      setOnsiteDaysPerWeek(saved.onsiteDaysPerWeek ?? "");
      setOfficeLocation(saved.officeLocation ?? "");
      setChampionProfile(saved.championProfile);
      setChampionSummary(saved.championSummary);
      // Old capped-pool responses are not valid full-population results.
    }
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    saveTalentRadarSession({
      client,
      title,
      text,
      location,
      budgetMax,
      excludeRemoteOnly,
      onsiteDaysPerWeek,
      officeLocation,
      championProfile,
      championSummary,
      championSkills,
      requirementsPreview,
      response: null,
    });
  }, [
    hydrated,
    client,
    title,
    text,
    location,
    budgetMax,
    excludeRemoteOnly,
    onsiteDaysPerWeek,
    officeLocation,
    championProfile,
    championSummary,
    championSkills,
    requirementsPreview,
  ]);

  const startSearch = () => fullSearch.start({ radar: {
        client_id: client!.id,
        text: championProfile ? undefined : text.trim() || undefined,
        champion_profile: championProfile ?? undefined,
        // Przy profilu nazwa roli pochodzi Z NIEGO (championSummary.role_name),
        // nie z ręcznego pola — nie ma po co jej dublować.
        title: championProfile
          ? championSummary?.role_name || undefined
          : title.trim() || undefined,
        // Przy wgranym profilu lokalizacja idzie z niego — pole obok jest
        // wtedy tylko do odczytu, żeby nie było drugiego źródła prawdy.
        location:
          (championProfile ? championSummary?.location : location.trim()) ||
          undefined,
        must_skills: previewCurrent ? splitSkills(requirementsPreview!.must) : championSkills?.must,
        nice_skills: previewCurrent ? splitSkills(requirementsPreview!.nice) : championSkills?.nice,
        requirements_reviewed: previewCurrent,
        budget_hourly_max:
          Number(budgetMax) > 0 ? Number(budgetMax) : undefined,
        exclude_remote_only: excludeRemoteOnly || undefined,
        // Pusty string → `undefined` (nie wiemy); `0` jest wysyłane, bo to
        // ZNANA wartość („wyłącznie zdalnie"), nie brak danych.
        onsite_days_per_week:
          onsiteDaysPerWeek.trim() !== "" ? Number(onsiteDaysPerWeek) : undefined,
        office_location: officeLocation.trim() || undefined,
  } });

  // Zmiana wejścia unieważnia POPRZEDNI błąd tak samo jak poprzednie wyniki:
  // komunikat „nie udało się" wiszący nad świeżo wybranym klientem opisywałby
  // zapytanie, którego już nie ma.
  const clearResults = () => {
    fullSearch.clear();
  };

  const hasProfile = championProfile !== null;
  const tooShort = text.trim().length < MIN_QUERY_LENGTH;
  const blocked = useMemo(() => {
    if (!client) return "Wybierz klienta.";
    if (!hasProfile && tooShort)
      return `Wgraj profil Championa ALBO wklej opis roli (min. ${MIN_QUERY_LENGTH} znaków).`;
    return null;
  }, [client, tooShort, hasProfile]);

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



  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Sourcing"
        title="Talent Radar"
        description="Wgraj profil Championa ALBO wklej treść requestu — jedno z dwóch. Przemielimy bazę kandydatów i pokażemy ranking, bez zakładania rekrutacji."
        density="compact"
      />
      <p className="text-sm text-muted-foreground">Nowy request — bez kontekstu zapisanej rekrutacji i jej hiring managera. Reguły klienta sprawdzamy dla wybranego klienta.</p>

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
            <Label htmlFor="tr-client">
              Klient <span className="text-destructive">*</span>
            </Label>
            <TalentRadarClientPicker
              value={client}
              onChange={(picked) => {
                setClient(picked);
                // Wyniki są prawdziwe WYŁĄCZNIE dla klienta, dla którego
                // policzono filtr dopuszczalności. Zostawienie ich po zmianie
                // klienta pokazywałoby listę odsianą przez blacklistę, NDA i
                // weto klienta A pod zdaniem „…wolno zaproponować TEMU
                // klientowi", wskazującym już na klienta B — czyli fałszywe
                // zapewnienie zgodności, dokładnie to, czemu obowiązkowy klient
                // ma zapobiegać.
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
          <div className="flex flex-col gap-2">
            <Label htmlFor="tr-onsite-days">Dni w biurze / tydzień</Label>
            <Input
              id="tr-onsite-days"
              type="number"
              min={0}
              max={7}
              value={onsiteDaysPerWeek}
              onChange={(e) => setOnsiteDaysPerWeek(e.target.value)}
              placeholder="np. 2 — 0 = tylko zdalnie"
              className="w-28"
            />
            <p className="text-xs text-muted-foreground">
              Bez tej liczby dealbreakery dni/miasta biura są nieaktywne —
              „nie wiemy" przechodzi. Wpisz 0, żeby zaznaczyć „tylko zdalnie".
            </p>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="tr-office-location">Miasto biura</Label>
            <Input
              id="tr-office-location"
              value={officeLocation}
              onChange={(e) => setOfficeLocation(e.target.value)}
              placeholder="np. Warszawa"
              maxLength={200}
            />
            <p className="text-xs text-muted-foreground">
              Osobne od pola „Lokalizacja" niżej — to konkretne miasto biura,
              porównywane z deklaracją kandydata przy dealbreakerze dni/miasta.
            </p>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="tr-location">Lokalizacja</Label>
            <Input
              id="tr-location"
              value={hasProfile ? (championSummary?.location ?? "") : location}
              onChange={(e) => setLocation(e.target.value)}
              readOnly={hasProfile}
              placeholder="np. Warszawa"
              maxLength={200}
            />
            <p className="text-xs text-muted-foreground">
              {hasProfile
                ? "Lokalizacja z profilu Championa — edytuj profil, żeby ją zmienić."
                : "Bez niej każdy kandydat dostaje „lokalizacja nieznana”, więc ta warstwa nikogo nie różnicuje."}
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

        {previewCurrent && requirementsPreview && (
          <section aria-label="Interpretacja wymagań" className="grid gap-x-8 gap-y-6 border-t border-border pt-6 md:grid-cols-3">
            <div>
              <h3 className="text-base font-semibold text-foreground">Sprawdź wymagania</h3>
              <p className="mt-1 text-sm text-muted-foreground">Popraw listy przed wyszukaniem. Nazwy rozdziel przecinkami. Pusta lista oznacza brak wymagań w tej kategorii.</p>
            </div>
            <div className="grid gap-4 md:col-span-2">
              <div className="space-y-2">
                <Label htmlFor="tr-must">Obowiązkowe</Label>
                <Textarea id="tr-must" value={requirementsPreview.must} rows={2} maxLength={4000}
                  onChange={e => { setRequirementsPreview({ ...requirementsPreview, must: e.target.value }); clearResults(); }} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="tr-nice">Dodatkowe</Label>
                <Textarea id="tr-nice" value={requirementsPreview.nice} rows={2} maxLength={4000}
                  onChange={e => { setRequirementsPreview({ ...requirementsPreview, nice: e.target.value }); clearResults(); }} />
              </div>
              {requirementsPreview.excluded.length > 0 && <p className="text-sm text-muted-foreground">Niewymagane: {requirementsPreview.excluded.join(", ")}. Nie wpływają na ocenę umiejętności.</p>}
              {requirementsPreview.uncertain.length > 0 && <p className="text-sm text-muted-foreground">Do rozstrzygnięcia: {requirementsPreview.uncertain.join(", ")}. Dodaj je do właściwej listy, jeżeli mają wpływać na ocenę.</p>}
            </div>
          </section>
        )}

        <div className="flex justify-end">
          <Button
            onClick={() => previewCurrent ? void startSearch() : void previewRequirements()}
            disabled={blocked !== null || fullSearch.running || interpreting}
          >
            <Radar className="mr-2 h-4 w-4" />
            {fullSearch.running ? "Szukam…" : interpreting ? "Sprawdzam…" : previewCurrent ? "Szukaj w całej bazie" : "Sprawdź wymagania"}
          </Button>
        </div>
      </div>

      <FullCandidateSearchResults
        data={fullSearch.data}
        offset={fullSearch.offset}
        onPage={fullSearch.setOffset}
        loading={fullSearch.loading}
        fetching={fullSearch.fetching}
        error={fullSearch.error}
        onRetry={() => { if (fullSearch.runId) void fullSearch.refresh(); else void startSearch(); }}
        canOpenProfile={canOpenProfile}
      />
    </div>
  );
}
