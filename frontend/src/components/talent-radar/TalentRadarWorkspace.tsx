"use client";

/**
 * Talent Radar — wklejasz treść requestu, dostajesz ranking bazy kandydatów.
 *
 * Trzy decyzje, które widać w kodzie i które nie są kosmetyczne:
 *
 * 1. Klient jest OBOWIĄZKOWY i pilnowany po stronie FE. Filtr dopuszczalności
 *    sprawdza względem niego blacklistę, NDA, konflikty konkurencyjne i weto
 *    hiring managera. Puszczenie żądania bez klienta dałoby 422 z dosłownym
 *    `client_id: Field required` (tak `extractErrorMsg` formatuje błędy body),
 *    czyli komunikat kontraktu API zamiast zdania po polsku.
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
 */

import { useMemo, useState } from "react";
import { Radar } from "lucide-react";
import { useMutation } from "@tanstack/react-query";

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
import { extractErrorMsg } from "@/lib/api";
import {
  talentRadarApi,
  type ChampionParseSummary,
  type TalentRadarSearchResponse,
} from "@/lib/talent-radar-api";
import { TalentRadarResults } from "@/components/talent-radar/TalentRadarResults";

/** Poniżej tego progu opis roli nie niesie sygnału wartego embeddingu. */
const MIN_QUERY_LENGTH = 30;

export function TalentRadarWorkspace() {
  const { showError } = useToast();
  const [client, setClient] = useState<ClientRef | null>(null);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [response, setResponse] = useState<TalentRadarSearchResponse | null>(
    null,
  );
  // Dealbreaker-switche: budżet podaje rekruter wprost (radar nie ma oferty);
  // nieznana stawka/preferencja kandydata przechodzi po stronie backendu.
  const [budgetMax, setBudgetMax] = useState("");
  const [budgetMargin, setBudgetMargin] = useState<0 | 15 | 30 | 50>(30);
  const [excludeRemoteOnly, setExcludeRemoteOnly] = useState(false);
  // Profil Championa z pliku (docx/pdf): rekruter dostaje go jako DOKUMENT —
  // wklejanie do pola tekstowego gubi strukturę (stawka, must/nice).
  const [championProfile, setChampionProfile] = useState<Record<
    string,
    unknown
  > | null>(null);
  const [championSummary, setChampionSummary] =
    useState<ChampionParseSummary | null>(null);
  const [parsingChampion, setParsingChampion] = useState(false);

  const search = useMutation({
    mutationFn: () =>
      talentRadarApi.search({
        client_id: client!.id,
        text: text.trim() || undefined,
        champion_profile: championProfile ?? undefined,
        title: title.trim() || undefined,
        top_k: 20,
        exclude_over_budget: Number(budgetMax) > 0 || undefined,
        budget_hourly_max: Number(budgetMax) > 0 ? Number(budgetMax) : undefined,
        budget_margin_pct: Number(budgetMax) > 0 ? budgetMargin : undefined,
        exclude_remote_only: excludeRemoteOnly || undefined,
      }),
    onSuccess: (data) => setResponse(data),
    onError: (error: unknown) => {
      setResponse(null);
      showError(extractErrorMsg(error));
    },
  });

  const tooShort = text.trim().length < MIN_QUERY_LENGTH;
  const blocked = useMemo(() => {
    if (!client)
      return "Wybierz klienta — bez niego nie sprawdzimy blacklist, NDA ani weta.";
    if (tooShort && !championProfile)
      return `Wklej opis roli (min. ${MIN_QUERY_LENGTH} znaków) albo wgraj plik profilu Championa.`;
    return null;
  }, [client, tooShort, championProfile]);

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
      // Stawka z profilu = budżet klienta na kandydata — pre-fill dla
      // dealbreakera (rekruter może nadpisać/wyczyścić).
      if (res.summary.rate_value && !budgetMax) {
        setBudgetMax(String(res.summary.rate_value));
      }
      setResponse(null);
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
        description="Wklej treść requestu albo opis roli. Przemielimy bazę kandydatów i pokażemy ranking — bez zakładania rekrutacji."
        density="compact"
      />

      <div className="flex flex-col gap-4 rounded-lg border border-border bg-card p-4">
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
                setResponse(null);
              }}
            />
            <p className="text-xs text-muted-foreground">
              Wymagany — względem niego sprawdzamy blacklistę, NDA, konflikty
              konkurencyjne i weto hiring managera.
            </p>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="tr-budget">Budżet PLN/h (opcjonalny dealbreaker)</Label>
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
              <select
                value={budgetMargin}
                onChange={(e) =>
                  setBudgetMargin(Number(e.target.value) as 0 | 15 | 30 | 50)
                }
                disabled={!(Number(budgetMax) > 0)}
                className="h-9 rounded-md border border-input bg-background px-2 text-sm disabled:opacity-50"
                title="Margines negocjacyjny — 0% ukrywa 44% realnie dowiezionych (zmierzone), default +30%"
                data-testid="tr-budget-margin"
              >
                <option value={0}>+0%</option>
                <option value={15}>+15%</option>
                <option value={30}>+30%</option>
                <option value={50}>+50%</option>
              </select>
              <label className="flex items-center gap-1.5 text-sm">
                <input
                  type="checkbox"
                  checked={excludeRemoteOnly}
                  onChange={(e) => setExcludeRemoteOnly(e.target.checked)}
                  data-testid="tr-exclude-remote-only"
                />
                ukryj „wyłącznie zdalnie”
              </label>
            </div>
            <p className="text-xs text-muted-foreground">
              Ukrywa tylko POZYTYWNIE znane przekroczenia/odmowy — brak danych
              zawsze przechodzi. Ukrytych policzymy w wynikach.
            </p>
          </div>
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
              Opcjonalna — wzmacnia dopasowanie.
            </p>
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <Label htmlFor="tr-champion-file">Profil Championa (plik)</Label>
          {championSummary ? (
            <div
              className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-muted px-3 py-2 text-sm"
              data-testid="tr-champion-loaded"
            >
              <span className="font-medium">
                {championSummary.role_name || "Profil wczytany"}
              </span>
              <span className="text-muted-foreground">
                {championSummary.must_count} must · {championSummary.nice_count}{" "}
                nice
                {championSummary.rate_value
                  ? ` · ${championSummary.rate_value} PLN/h`
                  : ""}
                {championSummary.location ? ` · ${championSummary.location}` : ""}
              </span>
              <button
                type="button"
                className="ml-auto text-xs text-muted-foreground underline hover:text-foreground"
                onClick={() => {
                  setChampionProfile(null);
                  setChampionSummary(null);
                  setResponse(null);
                }}
              >
                Usuń
              </button>
            </div>
          ) : (
            <input
              id="tr-champion-file"
              type="file"
              accept=".docx,.pdf"
              disabled={parsingChampion}
              onChange={onChampionFile}
              className="text-sm file:mr-3 file:rounded-md file:border file:border-border file:bg-background file:px-3 file:py-1.5 file:text-sm hover:file:bg-accent"
            />
          )}
          <p className="text-xs text-muted-foreground">
            {parsingChampion
              ? "Parsuję profil…"
              : "Docx/pdf od zespołu — odczytamy wymagania, stawkę i kontekst. Możesz też po prostu wkleić treść niżej."}
          </p>
        </div>

        <div className="flex flex-col gap-2">
          <Label htmlFor="tr-text">Treść requestu</Label>
          <Textarea
            id="tr-text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Wklej maila od klienta, opis stanowiska albo listę wymagań — jak leci."
            rows={8}
            maxLength={20_000}
          />
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>{blocked ?? "Gotowe do wyszukania."}</span>
            <span>{text.length.toLocaleString("pl-PL")} / 20 000</span>
          </div>
        </div>

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
      />
    </div>
  );
}
