"use client";

// Analityka kontraktów — wariant A z tabelą z wariantu B (decyzja Artura
// z 19.11.2026, makiety modułu Kontrakty): cztery liczby, „Najbliższe
// 3 miesiące”, smukła linia prognozy marży, tabela „kto ile przynosi”
// (Klienci · Konsultanci) i zwinięte rzadsze zestawienia na dole.
// Źródła danych i bramka „Wyniki firmy” bez zmian; okno 90 dni czyta listę
// kontraktów tymi samymi filtrami co ekran `/contracts`.

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { AlertTriangle, ArrowLeft } from "lucide-react";
import api from "@/lib/api";
import { RequirePermission } from "@/components/RequirePermission";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { AnalyticsForecast } from "@/components/contracts/analytics/AnalyticsForecast";
import { AnalyticsKeyFigures } from "@/components/contracts/analytics/AnalyticsKeyFigures";
import { AnalyticsMoreReports } from "@/components/contracts/analytics/AnalyticsMoreReports";
import {
  AnalyticsNextQuarter,
  type WindowPage,
} from "@/components/contracts/analytics/AnalyticsNextQuarter";
import { AnalyticsReport } from "@/components/contracts/analytics/AnalyticsReport";
import {
  addDaysIso,
  WINDOW_DAYS,
  type Forecast,
  type MarginRow,
  type MarginTotals,
  type UtilizationData,
} from "@/lib/contract-analytics";
import { formatIsoDatePl } from "@/lib/date-pl";
import { warsawToday } from "@/lib/warsaw-date";

/** Lista kontraktów w oknie: `status=active&status=ending` jak na `/contracts`. */
function fetchWindow(params: Record<string, unknown>): Promise<WindowPage> {
  return api
    .get("/api/contracts", {
      params: { status: ["active", "ending"], page_size: 100, ...params },
      paramsSerializer: { indexes: null },
    })
    .then((r) => r.data);
}

function ContractAnalytics() {
  const today = warsawToday();
  const until = addDaysIso(today, WINDOW_DAYS);

  // Kafle sum pytają o SUMY, nie o ranking: `margin-by-client` oddaje ranking
  // przycięty po marży, więc klient o wysokim przychodzie i niskiej marży
  // wypadał z sumy PRZYCHODU (audyt 18.09.2026: brakowało 217 060 zł).
  const totalsQ = useQuery<MarginTotals>({
    queryKey: ["contract-analytics-margin-totals"],
    queryFn: () => api.get("/api/contract-analytics/margin-totals").then((r) => r.data),
  });
  // Tabela pokazuje wszystkich klientów (do 100), nie pierwszą dwudziestkę.
  const clientQ = useQuery<MarginRow[]>({
    queryKey: ["contract-analytics-margin-client", 100],
    queryFn: () =>
      api.get("/api/contract-analytics/margin-by-client", { params: { limit: 100 } }).then((r) => r.data),
  });
  const utilQ = useQuery<UtilizationData>({
    queryKey: ["contract-analytics-utilization"],
    queryFn: () => api.get("/api/contract-analytics/utilization").then((r) => r.data),
  });
  const forecastQ = useQuery<Forecast>({
    queryKey: ["contract-analytics-forecast"],
    queryFn: () => api.get("/api/contract-analytics/revenue-forecast").then((r) => r.data),
  });
  const endingQ = useQuery<WindowPage>({
    queryKey: ["contract-analytics-window", "ending", today],
    queryFn: () => fetchWindow({ expiring_in_days: WINDOW_DAYS }),
  });
  const startingQ = useQuery<WindowPage>({
    queryKey: ["contract-analytics-window", "starting", today],
    queryFn: () => fetchWindow({ start_from: addDaysIso(today, 1), start_to: until }),
  });

  // Brak kursu FX w sumie albo w którymkolwiek wierszu: kwoty zależne od tych
  // pozycji pokazujemy jako „—”, a ekran mówi to wprost.
  const fxMissing =
    totalsQ.data?.fx_missing === true || (clientQ.data ?? []).some((row) => row.fx_missing === true);

  return (
    <div className="space-y-4">
      <header className="space-y-1">
        <Link
          href="/contracts"
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" aria-hidden />
          Kontrakty
        </Link>
        <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-1">
          <div className="min-w-0">
            <h1 className="text-[22px] font-semibold leading-7 tracking-tight text-foreground">
              Analityka kontraktów
            </h1>
            <p className="text-[13px] text-muted-foreground">
              Ile zarabiamy dziś i co zmieni się w najbliższych 3 miesiącach — aktywne i kończące się kontrakty.
            </p>
          </div>
          <p className="text-[12.5px] text-muted-foreground">Stan na {formatIsoDatePl(today)}</p>
        </div>
      </header>

      {fxMissing ? (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-lg border border-warning/25 bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>
            Dane finansowe są niepełne — pozycje bez kursu FX zostały pominięte. Kwoty i sumy zależne od tych
            pozycji pokazujemy jako „—”.
          </span>
        </div>
      ) : null}

      <AnalyticsKeyFigures totals={totalsQ} util={utilQ} fxMissing={fxMissing} />
      <AnalyticsNextQuarter ending={endingQ} starting={startingQ} today={today} until={until} />
      <AnalyticsForecast query={forecastQ} />
      <AnalyticsReport
        clients={clientQ}
        totals={totalsQ}
        util={utilQ}
        ending={endingQ}
        starting={startingQ}
        today={today}
      />
      <AnalyticsMoreReports />
    </div>
  );
}

export default function ContractAnalyticsPage() {
  return (
    // Lustro backendu: endpointy stoją za uprawnieniem „Wyniki firmy”, nie za
    // rolą. Bez tego osoba z Finansów widziałaby serię kart błędu 403 zamiast
    // jednego komunikatu.
    <RequirePermission
      permissions={["company_results"]}
      fallback={
        <QueryStateNotice
          state="forbidden"
          description="Analityka kontraktów wymaga uprawnienia „Wyniki firmy”. Poproś administratora o dostęp."
        />
      }
    >
      <ContractAnalytics />
    </RequirePermission>
  );
}
