"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  FileText,
  Gauge,
  Linkedin,
  Loader2,
  MessageSquare,
  Reply,
} from "lucide-react";
import type { ElementType } from "react";

import {
  LINKEDIN_CV_PER_DAY_TARGET,
  insightsActivityApi,
  insightsActivityQueryKeys,
  pctOf,
  ratio,
  type LinkedInPeriodKind,
  type LinkedInUserTotals,
} from "@/lib/insights-activity-api";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { DefinitionNote, count, pct } from "./InsightsFormat";
import { SectionError } from "./_shared";

interface Props {
  /** Startowa granulacja. Endpoint nie przyjmuje przesunięcia okna. */
  defaultPeriod?: LinkedInPeriodKind;
}

const PERIODS: Array<{ id: LinkedInPeriodKind; label: string }> = [
  { id: "week", label: "Tydzień" },
  { id: "month", label: "Miesiąc" },
  { id: "quarter", label: "Kwartał" },
  { id: "year", label: "Rok" },
];

/** Liczba dziesiętna po polsku albo „—”. */
function decimal(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("pl-PL", {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

const TILE_ACCENT = {
  info: "bg-info-muted text-info-muted-foreground",
  primary: "bg-primary/10 text-primary",
  linkedin: "bg-brand-linkedin/10 text-brand-linkedin",
  success: "bg-success-muted text-success-muted-foreground",
} as const;

function Tile({
  label,
  value,
  sub,
  icon: Icon,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  icon: ElementType;
  accent: keyof typeof TILE_ACCENT;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 shadow-xs">
      <div
        className={cn("mb-3 inline-flex rounded-lg p-2", TILE_ACCENT[accent])}
      >
        <Icon className="h-4 w-4" aria-hidden="true" />
      </div>
      <div className="text-2xl font-bold tabular-nums text-foreground">
        {value}
      </div>
      <div className="mt-0.5 text-sm text-muted-foreground">{label}</div>
      {sub && <div className="mt-1 text-xs text-muted-foreground">{sub}</div>}
    </div>
  );
}

/**
 * LinkedIn Performance — CV, wiadomości i odpowiedzi z ręcznej ewidencji.
 *
 * Trzy rzeczy, które ta sekcja robi INACZEJ niż backend, i każda z nich jest
 * naprawą, a nie ozdobą:
 *
 * 1. **Ilorazy liczone tutaj, nie brane z odpowiedzi.** `_safe_pct` w
 *    `linkedin_metrics.py` zwraca przy zerowym mianowniku `0.0`, więc osoba,
 *    która nie wysłała ani jednej wiadomości, dostaje „0% odpowiedzi" — werdykt
 *    zamiast braku danych. Tu zerowy mianownik daje `null`, czyli „—”.
 * 2. **Kafle są sumą tego, co widać w tabeli.** Liczymy je z `per_user`, nie
 *    z `totals`: kafel będący sumą innych liczb niż wiersze pod nim nie daje
 *    się zweryfikować wzrokiem. Przy okazji `days_reported` w ogóle nie ma
 *    w `totals`, a bez niego nie da się pokazać mianownika.
 * 3. **„CV/MD" nie jest procentem realizacji celu.** Mianownikiem jest liczba
 *    DNI ZARAPORTOWANYCH (`COUNT` wierszy), więc kto wypełnił raport za jeden
 *    dzień, ma najwyższy iloraz w zespole. To metryka, która NAGRADZA
 *    nieuzupełnianie raportu — dlatego obok ilorazu zawsze stoją liczby
 *    bezwzględne i liczba dni, a nagłówek mówi „na dzień raportowany”.
 *
 * Sekcja ma własny wybór granulacji i świadomie nie przyjmuje
 * `InsightsPeriodParams`: `/summary` liczy okno OD DZIŚ i nie zna przesunięcia,
 * więc pod `PeriodPicker`iem pokazywałaby bieżący miesiąc pod etykietą
 * poprzedniego.
 */
export function InsightsLinkedIn({ defaultPeriod = "month" }: Props = {}) {
  const [period, setPeriod] = useState<LinkedInPeriodKind>(defaultPeriod);

  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: insightsActivityQueryKeys.linkedinSummary(period),
    queryFn: () => insightsActivityApi.linkedinSummary(period),
  });

  const rows: LinkedInUserTotals[] = useMemo(
    () => data?.per_user ?? [],
    [data?.per_user],
  );

  const totals = useMemo(() => {
    const sum = (pick: (r: LinkedInUserTotals) => number) =>
      rows.reduce((acc, r) => acc + (pick(r) || 0), 0);
    return {
      cv: sum((r) => r.cv_added),
      messages: sum((r) => r.messages_sent),
      responses: sum((r) => r.responses_received),
      days: sum((r) => r.days_reported),
      people: rows.length,
    };
  }, [rows]);

  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: rows.length === 0,
  });

  return (
    <section className="bg-card rounded-xl border border-border p-6 shadow-xs">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
            <Linkedin className="h-5 w-5 text-brand-linkedin" />
            LinkedIn Performance
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {data
              ? `${data.date_from} – ${data.date_to} · ${count(totals.people)} os. raportowało`
              : "Ręczna ewidencja aktywności"}
          </p>
        </div>

        <div
          role="group"
          aria-label="Granulacja okresu LinkedIn"
          className="flex overflow-hidden rounded-lg border border-border"
        >
          {PERIODS.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => setPeriod(p.id)}
              aria-pressed={period === p.id}
              className={cn(
                "px-3 py-1.5 text-xs font-medium transition-colors",
                period === p.id
                  ? "bg-primary text-primary-foreground"
                  : "bg-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Bez tego zdania sekcja kłamie o oknie: `PeriodPicker` na górze zakładki
          domyślnie pokazuje POPRZEDNI zamknięty okres, a ten endpoint liczy
          zawsze od dziś i nie przyjmuje przesunięcia. */}
      <p className="mb-4 text-xs text-muted-foreground">
        Okno liczy backend od dzisiaj — sekcja pokazuje BIEŻĄCY okres i nie
        reaguje na przesunięcie wybrane u góry zakładki.
      </p>

      {viewState === "loading" ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : isBlockingViewState(viewState) ? (
        <SectionError
          label="LinkedIn Performance"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : viewState === "empty" ? (
        <div className="space-y-2 py-6 text-center">
          <p className="text-sm text-muted-foreground">
            Nikt nie zaraportował aktywności LinkedIn w tym okresie.
          </p>
          {/* Te dane wpisuje się RĘCZNIE (bulk-edit HoR/admina). Pustka znaczy
              „nikt nie wypełnił raportu", a nie „nikt nie pracował". */}
          <p className="mx-auto max-w-xl text-xs text-muted-foreground">
            Dane pochodzą z ręcznego raportu (bulk-edit w ustawieniach), nie z
            integracji z LinkedInem — brak wierszy znaczy, że raportu nie
            wypełniono, a nie że nie było aktywności.
          </p>
        </div>
      ) : (
        <div className="space-y-5">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Tile
              icon={FileText}
              accent="info"
              label="CV dodane"
              value={count(totals.cv)}
              sub={`w ${count(totals.days)} dniach raportowanych`}
            />
            <Tile
              icon={Gauge}
              accent="primary"
              label="CV na dzień raportowany"
              value={decimal(ratio(totals.cv, totals.days), 2)}
              // Świadomie NIE „% celu": mianownikiem są dni zaraportowane,
              // więc procent realizacji byłby procentem z ruchomej podstawy.
              sub={`cel ${LINKEDIN_CV_PER_DAY_TARGET} CV/dzień · ${count(totals.cv)} / ${count(totals.days)}`}
            />
            <Tile
              icon={MessageSquare}
              accent="linkedin"
              label="Wiadomości"
              value={count(totals.messages)}
              sub={`${decimal(ratio(totals.messages, totals.days), 1)} na dzień raportowany`}
            />
            <Tile
              icon={Reply}
              accent="success"
              label="Response rate"
              value={pct(pctOf(totals.responses, totals.messages), 1)}
              sub={`${count(totals.responses)} odp. / ${count(totals.messages)} wiad.`}
            />
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-xs uppercase text-muted-foreground">
                  <th className="py-2 pr-2 text-left font-medium">Osoba</th>
                  <th className="py-2 px-2 text-right font-medium">
                    Dni raport.
                  </th>
                  <th className="py-2 px-2 text-right font-medium">
                    CV dodane
                  </th>
                  <th className="py-2 px-2 text-right font-medium">CV/dzień</th>
                  <th className="py-2 px-2 text-right font-medium">
                    Wiadomości
                  </th>
                  <th className="py-2 px-2 text-right font-medium">
                    Wiad./dzień
                  </th>
                  <th className="py-2 pl-2 text-right font-medium">
                    Response rate
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.user_id} className="border-b border-border/50">
                    <td className="py-2 pr-2">
                      <div className="font-medium text-foreground">
                        {r.name}
                      </div>
                      {r.role && (
                        <div className="text-xs text-muted-foreground">
                          {r.role}
                        </div>
                      )}
                    </td>
                    <td className="py-2 px-2 text-right tabular-nums text-muted-foreground">
                      {count(r.days_reported)}
                    </td>
                    <td className="py-2 px-2 text-right tabular-nums">
                      {count(r.cv_added)}
                    </td>
                    <td className="py-2 px-2 text-right tabular-nums font-medium">
                      {decimal(ratio(r.cv_added, r.days_reported), 2)}
                    </td>
                    <td className="py-2 px-2 text-right tabular-nums">
                      {count(r.messages_sent)}
                    </td>
                    <td className="py-2 px-2 text-right tabular-nums">
                      {decimal(ratio(r.messages_sent, r.days_reported), 1)}
                    </td>
                    <td className="py-2 pl-2 text-right tabular-nums">
                      {pct(pctOf(r.responses_received, r.messages_sent), 1)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <DefinitionNote>
            Mianownikiem kolumn „na dzień” jest liczba DNI ZARAPORTOWANYCH, a
            nie dni roboczych — kto wypełnił raport za jeden dzień, ma najwyższy
            iloraz w zespole. Porównuj liczby bezwzględne razem z kolumną „Dni
            raport.”; sam iloraz nie mówi, ile ktoś przepracował.
          </DefinitionNote>
        </div>
      )}
    </section>
  );
}
