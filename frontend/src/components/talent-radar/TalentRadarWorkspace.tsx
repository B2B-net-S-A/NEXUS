"use client";

/** Talent Radar uses the shared, durable full-population search.
 * A click starts a scan; subsequent reads poll and paginate that same run.
 * Only the request form and actor-scoped run ID survive profile navigation.
 */

import { useEffect, useMemo, useState, useRef } from "react";
import { Radar } from "lucide-react";
import { useAuthStore } from "@/store/auth";
import { hasSectionAccess } from "@/lib/section-access";
import { SavedRequestSearch, type SavedRequestJobRef } from "./SavedRequestSearch";
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
import { extractErrorMsg, EMPTY_CHAMPION_PROFILE, type ChampionProfile } from "@/lib/api";
import { championErrorValidation, ChampionImportReview, ChampionImportButton, ChampionTemplateDownload, ChampionValidationPanel, type ChampionPreview, type ChampionValidation } from "@/components/ChampionIntake";
import {
  talentRadarApi,
  type ChampionParseSummary,
} from "@/lib/talent-radar-api";
import {
  loadTalentRadarSession,
  saveTalentRadarSession,
} from "@/lib/talent-radar-session";
import { FullCandidateSearchResults } from "@/components/talent-radar/FullCandidateSearchResults";
import {
  formatRadarRunCriteria,
  radarBudgetError,
  radarOfficeDaysError,
  type RadarRunCriteria,
} from "@/components/talent-radar/run-criteria";
import { addToRecruitmentSummary } from "@/components/v2/recruitment/AddToRecruitmentDialog";
import { useCanAddToRecruitment } from "@/components/v2/recruitment/useCanAddToRecruitment";

/** Poniżej tego progu opis roli nie niesie sygnału wartego embeddingu. */
const MIN_QUERY_LENGTH = 30;

/**
 * Dane z okna „Szukaj z requestu" na liście kandydatów (22.09.2026). Źródło
 * wymagań wybiera rekruter w oknie; tutaj radar startuje od razu od kroku
 * „Sprawdź wymagania" zamiast od pustego formularza.
 */
export interface TalentRadarInitialRequest {
  source: "text" | "file" | "job";
  /** Treść requestu (źródło `text`). */
  text?: string;
  /** Plik profilu Championa (źródło `file`) — parsujemy go od razu. */
  file?: File | null;
  /** Zapisana rekrutacja (źródło `job`). */
  job?: SavedRequestJobRef | null;
  client?: ClientRef | null;
  /** Pola formularza jako tekst — pusty = „nie wiem", jak w formularzu. */
  budget?: string;
  officeDays?: string;
  officeCity?: string;
}

export interface TalentRadarWorkspaceProps {
  /** Na ekranie „Kandydaci" tytuł i link powrotu daje rodzic. */
  embedded?: boolean;
  /**
   * Treść przeniesiona z innego miejsca (dawniej „Szukaj jak z requestu").
   * Wygrywa ze snapshotem sesji: to nowy request, więc kryteria i podgląd
   * wymagań poprzedniego wyszukiwania są czyszczone.
   */
  initialText?: string;
  /**
   * Request z okna „Szukaj z requestu". Pokazuje wyłącznie wybraną ścieżkę
   * (bez przełącznika „Nowy request / Zapisana rekrutacja") i sam uruchamia
   * sprawdzenie wymagań.
   */
  initial?: TalentRadarInitialRequest;
}

export function TalentRadarWorkspace({ embedded = false, initialText, initial }: TalentRadarWorkspaceProps = {}) {
  const user = useAuthStore(s => s.user);
  const canReadJobs = hasSectionAccess(user, "pipeline", "read");
  const [mode, setMode] = useState<"adhoc" | "saved">(initial?.source === "job" ? "saved" : "adhoc");
  useEffect(() => {
    // Tekst przeniesiony z wyszukiwarki to NOWY request — nie przełączaj na
    // zapamiętaną „Zapisaną rekrutację", bo wklejona treść by zniknęła z oczu.
    if (!user?.id || initialText?.trim() || initial) return;
    try { if (sessionStorage.getItem(`nexus-radar-mode:${user.id}`) === "saved") setMode("saved"); } catch {}
  }, [user?.id, initialText, initial]);
  if (initial) {
    return initial.source === "job" && initial.job && canReadJobs
      ? <SavedRequestSearch initialJob={initial.job} hidePicker />
      : <AdHocTalentRadarWorkspace embedded={embedded} initial={initial} />;
  }
  const choose = (value: "adhoc" | "saved") => {
    setMode(value);
    if (user?.id) { try { sessionStorage.setItem(`nexus-radar-mode:${user.id}`, value); } catch {} }
  };
  return <div className="space-y-4">
    {canReadJobs && <div className="flex gap-2" aria-label="Źródło requestu">
      <Button variant={mode === "adhoc" ? "primary" : "outline"} onClick={() => choose("adhoc")}>Nowy request</Button>
      <Button variant={mode === "saved" ? "primary" : "outline"} onClick={() => choose("saved")}>Zapisana rekrutacja</Button>
    </div>}
    {mode === "saved" && canReadJobs ? <SavedRequestSearch /> : <AdHocTalentRadarWorkspace embedded={embedded} initialText={initialText} />}
  </div>;
}

function AdHocTalentRadarWorkspace({ embedded = false, initialText, initial }: TalentRadarWorkspaceProps) {
  const { showError, showSuccess } = useToast();
  const canAddToRecruitment = useCanAddToRecruitment();
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
  // Toast RAZ na epizod błędu: w czasie blipu sieci każdy nieudany poll daje
  // nowy obiekt błędu, a toast przy każdym z nich zasypywał ekran. Epizod
  // kończy się, gdy błąd zniknie (udany odczyt, nowy bieg, wyczyszczenie).
  const errorToastShown = useRef(false);
  useEffect(() => {
    if (!fullSearch.error) { errorToastShown.current = false; return; }
    setIntakeValidation(championErrorValidation(fullSearch.error));
    if (errorToastShown.current) return;
    errorToastShown.current = true;
    showError(extractErrorMsg(fullSearch.error));
  }, [fullSearch.error, showError]);
  // Kryteria, z którymi uruchomiono wyświetlany bieg („Kryteria biegu").
  const [runCriteria, setRunCriteria] = useState<RadarRunCriteria | null>(null);
  // Dealbreaker-switche: budżet podaje rekruter wprost (radar nie ma oferty)
  // i SAMA jego obecność działa jako twardy sufit — bez marginesu, bez
  // osobnego uzbrajania (decyzja produktowa 19.08). Nieznana stawka/
  // preferencja kandydata przechodzi po stronie backendu.
  const [budgetMax, setBudgetMax] = useState("");
  // Odczyt aktualnej wartości po `await` w „Sprawdź wymagania” — domknięcie
  // widziałoby stan sprzed zapytania.
  const budgetMaxRef = useRef(budgetMax);
  budgetMaxRef.current = budgetMax;
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
  const [intakePreview, setIntakePreview] = useState<ChampionPreview | null>(null);
  // A parsed document and "Popraw profil" (the current profile) share one
  // review dialog; only the document may send its rate text back.
  const [intakeFromDocument, setIntakeFromDocument] = useState(false);
  const [intakeValidation, setIntakeValidation] = useState<ChampionValidation>();
  const importedValues = useRef<Record<string, string>>({});
  const currentForImport = (): ChampionProfile | undefined => {
    if (!championProfile && !budgetMax && !onsiteDaysPerWeek && !officeLocation) return undefined;
    const cp = structuredClone({ ...EMPTY_CHAMPION_PROFILE, ...(championProfile ?? {}) }) as ChampionProfile;
    cp.basics = { ...cp.basics, rate_value: budgetMax ? Number(budgetMax) : null, onsite_days_per_week: onsiteDaysPerWeek !== "" ? Number(onsiteDaysPerWeek) : null, candidate_location_pref: officeLocation || null };
    return cp;
  };
  const applyIntake = (cp: ChampionProfile, result?: ChampionValidation) => {
    setChampionProfile(cp as unknown as Record<string, unknown>); setIntakeValidation(result);
    setChampionSkills({ must: cp.stack.must.map(s => s.name), nice: cp.stack.nice.map(s => s.name) });
    setChampionSummary({ role_name: cp.basics.role_name ?? null, must_count: cp.stack.must.length, nice_count: cp.stack.nice.length, rate_value: cp.basics.rate_value ?? null, work_mode: cp.basics.work_mode ?? null, location: cp.basics.candidate_location_pref ?? null });
    const next = { budget: String(cp.basics.rate_value ?? ""), days: String(cp.basics.onsite_days_per_week ?? ""), city: cp.basics.candidate_location_pref ?? "" };
    for (const [key, previous] of Object.entries({ budget: budgetMax, days: onsiteDaysPerWeek, city: officeLocation })) {
      if (!previous || previous !== next[key as keyof typeof next] || importedValues.current[key] === previous) importedValues.current[key] = next[key as keyof typeof next];
    }
    setBudgetMax(next.budget); setOnsiteDaysPerWeek(next.days); setOfficeLocation(next.city);
    clearResults();
  };
  const [parsingChampion, setParsingChampion] = useState(false);
  const [requirementsPreview, setRequirementsPreview] = useState<{
    source: string; must: string; nice: string; excluded: string[]; uncertain: string[];
  } | null>(null);
  const [interpreting, setInterpreting] = useState(false);
  // Podpowiedzi z treści requestu. Budżet wpisujemy RAZ na daną treść i tylko
  // do pustego pola — ponowne „Sprawdź wymagania” nie nadpisze stawki, którą
  // rekruter wyczyścił albo poprawił.
  const budgetFilledFromText = useRef<string | null>(null);
  const [budgetHint, setBudgetHint] = useState<number | null>(null);
  const [remoteHint, setRemoteHint] = useState(false);
  // Po uruchomieniu przeglądu formularz zwija się do jednej linii — wyniki
  // stają na górze ekranu. „Zmień kryteria” rozwija go z powrotem.
  const [editingCriteria, setEditingCriteria] = useState(false);
  const requirementSource = JSON.stringify([text, title, championProfile]);
  const previewCurrent = requirementsPreview?.source === requirementSource;
  const splitSkills = (value: string) => value.split(/[,;\n]/).map(s => s.trim()).filter(Boolean);
  /** Dopisuje nierozstrzygnięte umiejętności do listy (przecinkiem) i zdejmuje je z „do rozstrzygnięcia”. */
  const moveUncertain = (names: string[], level: "must" | "nice") => {
    if (!requirementsPreview || names.length === 0) return;
    const current = requirementsPreview[level];
    const present = new Set(splitSkills(current).map(s => s.toLowerCase()));
    const additions = names.filter(n => !present.has(n.toLowerCase()));
    const base = current.trim().replace(/[,;]\s*$/, "");
    const next = additions.length === 0 ? current : base ? `${base}, ${additions.join(", ")}` : additions.join(", ");
    const moved = new Set(names);
    setRequirementsPreview({ ...requirementsPreview, [level]: next, uncertain: requirementsPreview.uncertain.filter(u => !moved.has(u)) });
    clearResults();
  };
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
      const suggested = championProfile ? null : parsed.suggestions?.budget_max_pln_hour ?? null;
      if (suggested !== null && suggested > 0 && !budgetMaxRef.current.trim() && budgetFilledFromText.current !== text) {
        budgetFilledFromText.current = text;
        setBudgetMax(String(suggested));
        setBudgetHint(suggested);
      }
      setRemoteHint(!championProfile && parsed.suggestions?.remote_only === true);
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
      importedValues.current = saved.championImportedValues ?? {};
      setRunCriteria(saved.runCriteria ?? null);
      // Old capped-pool responses are not valid full-population results.
    }
    if (initialText?.trim()) {
      setText(initialText);
      setRunCriteria(null);
      setRequirementsPreview(null);
      setChampionSkills(null);
    }
    if (initial) {
      // Nowy request z okna: nic ze snapshotu poprzedniego wyszukiwania nie
      // może się do niego przykleić (profil, wymagania, kryteria biegu).
      setText(initial.source === "text" ? initial.text ?? "" : "");
      setTitle("");
      setLocation("");
      setClient(initial.client ?? null);
      setBudgetMax(initial.budget ?? "");
      setOnsiteDaysPerWeek(initial.officeDays ?? "");
      setOfficeLocation(initial.officeCity ?? "");
      setExcludeRemoteOnly(false);
      setChampionProfile(null);
      setChampionSummary(null);
      setChampionSkills(null);
      importedValues.current = {};
      setRequirementsPreview(null);
      setRunCriteria(null);
      fullSearch.clear();
      autoCheckPending.current = true;
      if (initial.source === "file" && initial.file) void parseChampionFile(initial.file);
    }
    setHydrated(true);
    // Tylko przy montowaniu: nowy tekst z wyszukiwarki montuje radar od nowa
    // (`key` w CandidatesWorkspace), więc zmiana propsa nie musi tu wracać.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      championImportedValues: importedValues.current,
      requirementsPreview,
      runCriteria,
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
    runCriteria,
  ]);

  const startSearch = async () => {
    // Zwiń formularz kryteriów (#1597) — wyniki biegu mają być tym, co widać.
    setEditingCriteria(false);
    const criteria: RadarRunCriteria = {
      clientName: client!.name,
      budget: Number(budgetMax) > 0 ? Number(budgetMax) : null,
      location:
        (championProfile ? championSummary?.location : location.trim()) || null,
      officeDays: onsiteDaysPerWeek.trim() !== "" ? Number(onsiteDaysPerWeek) : null,
      officeLocation: officeLocation.trim() || null,
      excludeRemoteOnly,
    };
    const run = await fullSearch.start({ radar: {
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
    // Kryteria zmieniamy dopiero po przyjęciu biegu — odmowa startu zostawia
    // na ekranie poprzedni bieg, więc i jego kryteria.
    if (run) setRunCriteria(criteria);
  };

  // Zmiana wejścia unieważnia POPRZEDNI błąd tak samo jak poprzednie wyniki:
  // komunikat „nie udało się" wiszący nad świeżo wybranym klientem opisywałby
  // zapytanie, którego już nie ma.
  //
  // Dotyczy KAŻDEGO pola, które wchodzi do requestu (budżet, dni, miasto
  // biura, lokalizacja, „wyłącznie zdalnie”, treść, nazwa roli) — nie tylko
  // klienta. Wyniki pod zmienionym formularzem czytały się jak policzone dla
  // nowych kryteriów.
  const clearResults = () => {
    fullSearch.clear();
    setRunCriteria(null);
  };

  const budgetError = radarBudgetError(budgetMax);
  const officeDaysError = radarOfficeDaysError(onsiteDaysPerWeek);

  const hasProfile = championProfile !== null;
  const formCollapsed = fullSearch.runId !== null && !editingCriteria;
  const criteriaSummary = useMemo(() => {
    const request = hasProfile
      ? championSummary?.role_name || "Profil Championa"
      : (() => { const flat = text.trim().replace(/\s+/g, " "); return flat.length > 80 ? `${flat.slice(0, 80)}…` : flat; })();
    const must = previewCurrent && requirementsPreview ? requirementsPreview.must : championSkills?.must.join(", ") ?? "";
    return [client?.name, request, must.trim() ? `obowiązkowe: ${must.trim()}` : null].filter(Boolean).join(" · ");
  }, [hasProfile, championSummary, text, previewCurrent, requirementsPreview, championSkills, client]);
  const tooShort = text.trim().length < MIN_QUERY_LENGTH;
  const blocked = useMemo(() => {
    if (!client) return "Wybierz klienta.";
    if (!hasProfile && tooShort)
      return `Wgraj profil Championa ALBO wklej opis roli (min. ${MIN_QUERY_LENGTH} znaków).`;
    // Szczegół stoi przy polu; tu tylko wskazanie, dlaczego start jest zablokowany.
    if (budgetError || officeDaysError) return "Popraw liczby zaznaczone w formularzu.";
    return null;
  }, [client, tooShort, hasProfile, budgetError, officeDaysError]);

  const onChampionFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null;
    // Reset inputu OD RAZU: bez tego po błędzie parsowania przeglądarka nie
    // odpali onChange przy ponownym wyborze tego samego pliku (recenzja #1204).
    e.target.value = "";
    if (!f) return;
    await parseChampionFile(f);
  };

  async function parseChampionFile(f: File) {
    setParsingChampion(true);
    try {
      const res = await talentRadarApi.parseChampion(f);
      setIntakeFromDocument(true);
      setIntakePreview({ champion_profile: res.champion_profile as unknown as ChampionProfile, validation: res.validation });
    } catch (error: unknown) {
      showError(extractErrorMsg(error));
    } finally {
      setParsingChampion(false);
    }
  }

  // Okno „Szukaj z requestu" prosi o wymagania od razu: gdy formularz jest
  // kompletny (klient + treść albo zatwierdzony profil) i nic nie czeka na
  // decyzję rekrutera (przegląd profilu z pliku), jeden raz uruchamiamy
  // „Sprawdź wymagania". Blokada (np. za krótka treść) zostaje widoczna
  // w formularzu — nie próbujemy jej obchodzić.
  const autoCheckPending = useRef(false);
  const previewRequirementsRef = useRef(previewRequirements);
  previewRequirementsRef.current = previewRequirements;
  useEffect(() => {
    if (!hydrated || !autoCheckPending.current) return;
    if (intakePreview || parsingChampion || interpreting) return;
    autoCheckPending.current = false;
    // Formularz niekompletny (np. przegląd profilu zamknięty bez zatwierdzenia,
    // za krótka treść) — powód stoi przy formularzu, rekruter kończy ręcznie.
    if (blocked !== null) return;
    void previewRequirementsRef.current();
  }, [hydrated, intakePreview, parsingChampion, interpreting, blocked]);



  return (
    <div className="flex flex-col gap-6">
      <div className="flex gap-2"><ChampionTemplateDownload />{hasProfile && <><Button variant="outline" size="sm" onClick={() => { setIntakeFromDocument(false); setIntakePreview({ champion_profile: currentForImport()!, validation: intakeValidation }); }}>Popraw profil</Button><ChampionImportButton current={currentForImport()} onApply={applyIntake} /></>}</div>
      {intakePreview && <ChampionImportReview initial={intakePreview} current={currentForImport()} sourceIsDocument={intakeFromDocument} onApply={applyIntake} onClose={() => setIntakePreview(null)} />}
      <ChampionValidationPanel validation={intakeValidation} />
      {!embedded && <PageHeader
        eyebrow="Sourcing"
        title="Talent Radar"
        description="Wgraj profil Championa ALBO wklej treść requestu — jedno z dwóch. Przemielimy bazę kandydatów i pokażemy ranking, bez zakładania rekrutacji."
        density="compact"
      />}
      <p className="text-sm text-muted-foreground">Nowy request — bez kontekstu zapisanej rekrutacji i jej hiring managera. Reguły klienta sprawdzamy dla wybranego klienta.</p>

      {formCollapsed ? (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card px-4 py-3" data-testid="tr-criteria-summary">
          <p className="min-w-0 flex-1 truncate text-sm text-foreground">{criteriaSummary}</p>
          <Button type="button" variant="outline" size="sm" onClick={() => setEditingCriteria(true)}>Zmień kryteria</Button>
        </div>
      ) : (
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
                  setIntakeValidation(undefined);
                  if (importedValues.current.budget === budgetMax) setBudgetMax("");
                  if (importedValues.current.days === onsiteDaysPerWeek) setOnsiteDaysPerWeek("");
                  if (importedValues.current.city === officeLocation) setOfficeLocation("");
                  importedValues.current = {};
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
                onChange={(e) => { setText(e.target.value); clearResults(); }}
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
                // klienta pokazywałoby listę odsianą wetem i oznaczoną
                // konfliktami klienta A pod zdaniem „…wolno zaproponować TEMU
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
                onChange={(e) => { delete importedValues.current.budget; setBudgetMax(e.target.value); clearResults(); }}
                placeholder="np. 150"
                aria-invalid={budgetError ? true : undefined}
                aria-describedby={budgetError ? "tr-budget-error" : undefined}
                className="w-28"
              />
              <label className="flex items-center gap-1.5 text-sm">
                <input
                  type="checkbox"
                  checked={excludeRemoteOnly}
                  onChange={(e) => { setExcludeRemoteOnly(e.target.checked); clearResults(); }}
                  data-testid="tr-exclude-remote-only"
                />
                praca z biura — ukryj „wyłącznie zdalnie”
              </label>
            </div>
            {budgetError && (
              <p id="tr-budget-error" className="text-xs text-destructive">{budgetError}</p>
            )}
            {budgetHint !== null && budgetMax === String(budgetHint) && !championSummary?.rate_value && <p className="text-xs text-muted-foreground" data-testid="tr-budget-hint">Stawkę {budgetHint} PLN/h wzięliśmy z treści requestu — popraw ją, jeżeli to nie budżet.</p>}

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
              onChange={(e) => { delete importedValues.current.days; setOnsiteDaysPerWeek(e.target.value); clearResults(); }}
              placeholder="np. 2 — 0 = tylko zdalnie"
              aria-invalid={officeDaysError ? true : undefined}
              aria-describedby={officeDaysError ? "tr-onsite-days-error" : undefined}
              className="w-28"
            />
            {officeDaysError && (
              <p id="tr-onsite-days-error" className="text-xs text-destructive">{officeDaysError}</p>
            )}
            {remoteHint && previewCurrent && <p className="text-xs text-muted-foreground" data-testid="tr-remote-hint">W treści: praca zdalna.</p>}

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
              onChange={(e) => { delete importedValues.current.city; setOfficeLocation(e.target.value); clearResults(); }}
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
              onChange={(e) => { setLocation(e.target.value); clearResults(); }}
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
                onChange={(e) => { setTitle(e.target.value); clearResults(); }}
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
              {requirementsPreview.uncertain.length > 0 && <div className="space-y-2" aria-label="Do rozstrzygnięcia">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm text-muted-foreground">Do rozstrzygnięcia — przenieś na właściwą listę, jeżeli mają wpływać na ocenę:</p>
                  <Button type="button" size="sm" variant="outline" onClick={() => moveUncertain(requirementsPreview.uncertain, "must")}>Wszystkie do obowiązkowych</Button>
                </div>
                <ul className="flex flex-wrap gap-2">
                  {requirementsPreview.uncertain.map(name => <li key={name} className="flex items-center gap-1 rounded-full border border-border bg-muted py-0.5 pl-3 pr-1 text-sm">
                    <span>{name}</span>
                    <Button type="button" size="sm" variant="ghost" className="h-6 px-2 text-xs" aria-label={`${name} do obowiązkowych`} onClick={() => moveUncertain([name], "must")}>→ obowiązkowe</Button>
                    <Button type="button" size="sm" variant="ghost" className="h-6 px-2 text-xs" aria-label={`${name} do dodatkowych`} onClick={() => moveUncertain([name], "nice")}>→ dodatkowe</Button>
                  </li>)}
                </ul>
              </div>}
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
      )}

      {fullSearch.runId && runCriteria && (
        <p
          className="rounded-md border border-border bg-muted px-3 py-2 text-sm text-muted-foreground"
          data-testid="tr-run-criteria"
        >
          <span className="font-medium text-foreground">Kryteria biegu:</span>{" "}
          {formatRadarRunCriteria(runCriteria, fullSearch.data?.budget_hourly)}
        </p>
      )}

      <FullCandidateSearchResults
        data={fullSearch.data}
        offset={fullSearch.offset}
        onPage={fullSearch.setOffset}
        loading={fullSearch.loading}
        fetching={fullSearch.fetching}
        error={fullSearch.error}
        onRetry={() => { if (fullSearch.runId) void fullSearch.refresh(); else void startSearch(); }}
        // A stale (409), expired (404) or failed run cannot be re-read into a
        // current ranking — offer a new run with the current, checked form
        // (otherwise the main button above is the way to check and start).
        needsNewRun={fullSearch.needsNewRun}
        onRestart={blocked === null && previewCurrent ? () => void startSearch() : undefined}
        canOpenProfile={canOpenProfile}
        addToRecruitment={canAddToRecruitment ? { source: "talent_radar", onAdded: result => showSuccess(addToRecruitmentSummary(result)) } : undefined}
      />
    </div>
  );
}
