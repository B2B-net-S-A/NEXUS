"use client";

import { Suspense, useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { QueryStateNotice } from "@/components/ds";
import { RequirePermission } from "@/components/RequirePermission";
import { FinanceArchiveTab } from "@/components/finance/FinanceArchiveTab";
import { FinanceResultsTab } from "@/components/finance/FinanceResultsTab";
import { MdImportWorkspace } from "@/components/finance/MdImportWorkspace";
import {
  ORDER_CHANGES_SUMMARY_KEY,
  ORDER_CHANGES_URL_KEYS,
  OrderChangesTab,
} from "@/components/finance/OrderChangesTab";
import {
  ORDER_PDFS_URL_KEYS,
  OrderPdfsTab,
} from "@/components/finance/OrderPdfsTab";
import { financeApi, type OrderPdfRef } from "@/lib/api/finance";
import { ORDER_CHANGES_POLL_MS } from "@/lib/polling";
import { hasPermission } from "@/lib/permissions";
import { hasSectionAccess } from "@/lib/section-access";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";

import { parseFinanceView, type FinanceViewMode as ViewMode } from "@/lib/finance-view";
import { FinanceSalesInvoicesTab } from "@/components/clients/invoicing/FinanceSalesInvoicesTab";
import { RateDivergencesTab } from "@/components/finance/RateDivergencesTab";
import { useInvoicingModule } from "@/lib/api/client-invoicing";
import {
  APPROVED_EXPENSES_URL_KEYS,
  ApprovedExpensesTab,
} from "@/components/finance/ApprovedExpensesTab";
import { useHrConfig } from "@/lib/api/hr";

/** Jedno zdanie pod tytułem — mówi, co pokazuje wybrana zakładka. */
const VIEW_DESCRIPTION: Record<ViewMode, string> = {
  results: "Miesięczne wyniki finansowe kontraktorów — koszt, przychód i marża",
  archive:
    "Archiwum importów wyników — każdy wgrany plik zostaje, poprzednią wersję można przywrócić",
  md: "Miesięczne raporty zużycia MD zasilające budżety zamówień klientów",
  "order-changes":
    "Bieżący, comiesięczny audyt zdarzeń w zamówieniach na potrzeby rozliczeń",
  "order-pdfs":
    "PDF-y nowych zamówień, przedłużeń i aneksów według miesiąca rozpoczęcia i klienta",
  "sales-invoices":
    "Faktury do klientów z KSeF dopasowane do zamówień, wpłaty z wyciągu i zaległości",
  "rate-divergences":
    "Nocny raport: gdzie stawka z kontraktu różni się od stawki linii zamówienia MD",
  "approved-expenses":
    "Zatwierdzone wydatki do rozliczenia, rejestr subskrypcji i faktury kosztowe bez zgody",
};

/**
 * FE-N09 (audyt 22.09 r2): widok idzie za `?view=` także przy MIĘKKIEJ
 * nawigacji — link (np. z powiadomienia) do `/finance?view=order-changes`
 * przy otwartym module nie odmontowuje strony, więc odczyt `window.location`
 * przy montowaniu go nie widział. Efekt zależy od WARTOŚCI parametru; mały
 * komponent w `Suspense`, żeby `useSearchParams` nie wymusił granicy
 * Suspense wokół całej strony.
 */
function FinanceViewSync({ onView }: { onView: (view: ViewMode) => void }) {
  const searchParams = useSearchParams();
  const raw = searchParams ? searchParams.get("view") : undefined;
  useEffect(() => {
    // `undefined` = poza routerem App (testy) — zostaje odczyt przy montowaniu.
    if (raw === undefined) return;
    onView(parseFinanceView(raw));
  }, [raw, onView]);
  return null;
}

/**
 * /finance — moduł „Finanse", trzy powierzchnie pod jedną trasą:
 *
 *  • „Wyniki miesięczne" — koszt / przychód / marża kontraktorów z arkusza,
 *  • „Archiwum"          — historia wgranych plików + przywracanie wersji,
 *  • „Import zużycia MD"  — miesięczne raporty zasilające budżety MD zamówień
 *                           wielo-konsultantowych (PR #1162),
 *  • „Zmiany w zamówieniach" — comiesięczny audyt wejść, zejść, zmian stawek
 *                           i braków kolejnego zamówienia (tylko odczyt),
 *  • „Zamówienia PDF"     — PDF-y zamówień po miesiącu startu i kliencie,
 *                           z nazwą pliku z nazwiskiem i okresem.
 *
 * Dwa niezależne moduły trafiły na tę samą trasę w tym samym tygodniu. Zamiast
 * rozdzielać je na dwa adresy i dwa wpisy w nawigacji (obie nazwane „Finanse",
 * obie dla tych samych ról — użytkownik musiałby zgadywać, w którym siedzi
 * jego arkusz), stoją jako zakładki. Przełącznik jest ten sam co w module
 * Kontrakty.
 *
 * „Moduł Finanse” otwiera wszystkie zakładki. Samo „Zamówienia: zmiany, PDF-y,
 * import MD” (rola Back office, decyzja Artura 04.11.2026) otwiera tylko trzy
 * o zamówieniach. `RequirePermission` to warstwa UX; bramką jest API.
 *
 * Stan zakładki żyje w URL przez History API, nie `useSearchParams` — ten drugi
 * wymusza w Next 15 granicę Suspense wokół całej strony (ten sam powód co
 * w /contracts, skąd pochodzi przełącznik).
 */
export default function FinancePage() {
  const user = useAuthStore((state) => state.user);
  const impersonating = useAuthStore((state) => state.realUser !== null);
  const [view, setView] = useState<ViewMode>("results");
  const hasModule = hasPermission(user, "finance_module");
  const [mounted, setMounted] = useState(false);
  // Podgląd jako użytkownik jest zawsze read-only, także gdy target ma
  // Finance=write. Backend odrzuca takie mutacje; UI nie może sugerować, że
  // import, restore lub edycja komórek zadziałają.
  const canWrite =
    !impersonating && hasSectionAccess(user, "finance", "write");
  // „Faktury do klientów” (E8) tylko przy włączonym module (admin widzi zawsze).
  const invoicingOpen = useInvoicingModule(hasModule).data?.open === true;
  // „Wydatki ze zgodą” (Zgody, etap 3) tylko przy otwartym module „Zgody”.
  const approvalsOpen =
    useHrConfig(hasModule).data?.open_modules?.approvals === true;
  // Import MD: `orders_work`, nie zapis sekcji — sekcji Back office nie ma.
  const canImportMd = !impersonating && hasPermission(user, "orders_work");
  const fallbackView: ViewMode = hasModule ? "results" : "order-changes";
  const visibleView =
    (view === "md" && !canImportMd) ||
    (view === "results" && !hasModule) ||
    (view === "archive" && !hasModule) ||
    (view === "sales-invoices" && !invoicingOpen) ||
    (view === "rate-divergences" && !hasModule) ||
    (view === "approved-expenses" && !approvalsOpen)
      ? fallbackView
      : view;

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setView(parseFinanceView(params.get("view")));
    setMounted(true);
  }, []);

  // Badge „do zrobienia" przy zakładce — zmiany bieżącego miesiąca. Liczony
  // przez serwer; odhaczenie unieważnia ten klucz, więc spada od razu.
  const summary = useQuery({
    queryKey: ORDER_CHANGES_SUMMARY_KEY,
    queryFn: async () => (await financeApi.getOrderChangesSummary()).data,
    enabled: mounted,
    refetchOnWindowFocus: true,
    refetchInterval: ORDER_CHANGES_POLL_MS,
  });
  const todoBadge = summary.data?.todo ?? 0;

  /** „Otwórz w Zamówienia PDF" — miesiąc i klient pliku, nic więcej z adresu. */
  function openInPdfs(pdf: OrderPdfRef) {
    const params = new URLSearchParams(window.location.search);
    params.set("pdfMonth", pdf.month);
    params.set("pdfClient", String(pdf.client_id));
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}?${params.toString()}`,
    );
    changeView("order-pdfs");
  }

  function changeView(next: ViewMode) {
    setView(next);
    const params = new URLSearchParams(window.location.search);
    if (next === "results") {
      params.delete("view");
    } else {
      params.set("view", next);
    }
    // Podzakładka, miesiąc i filtry należą do „Zmian w zamówieniach" — w innym
    // widoku zostałyby w adresie jako martwy parametr.
    if (next !== "order-changes") {
      ORDER_CHANGES_URL_KEYS.forEach((key) => params.delete(key));
    }
    if (next !== "order-pdfs") {
      ORDER_PDFS_URL_KEYS.forEach((key) => params.delete(key));
    }
    if (next !== "approved-expenses") {
      APPROVED_EXPENSES_URL_KEYS.forEach((key) => params.delete(key));
    }
    const query = params.toString();
    window.history.replaceState(
      null,
      "",
      query ? `${window.location.pathname}?${query}` : window.location.pathname,
    );
  }

  return (
    <RequirePermission
      permissions={["orders_work", "finance_module"]}
      fallback={
        <QueryStateNotice
          state="forbidden"
          description="Ten ekran wymaga uprawnienia do Modułu Finanse albo do zamówień. Poproś administratora o dostęp."
        />
      }
    >
      <Suspense fallback={null}>
        <FinanceViewSync onView={setView} />
      </Suspense>
      <div className="space-y-3.5">
        {/* Tytuł i opis w jednej linii, zakładki pod spodem (makiety 02.10.2026)
            — nagłówek z nadtytułem i osobnym opisem spychał tabelę w dół. */}
        <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 className="font-display text-xl font-semibold leading-tight tracking-tight">
            Finanse
          </h1>
          <p className="min-w-0 text-[13px] text-muted-foreground">
            {VIEW_DESCRIPTION[visibleView]}
          </p>
        </header>

        <div
          role="tablist"
          aria-label="Tryb modułu Finanse"
          // Pięć długich etykiet (~460 px) — poniżej `sm` przewijanie w poziomie
          // zamiast wypychania strony (audyt 23.09.2026, P1-12).
          data-help="finance.modes"
          className="flex max-w-full gap-0.5 overflow-x-auto border-b border-border"
        >
          {hasModule && (
            <ModeButton
              active={visibleView === "results"}
              onClick={() => changeView("results")}
            >
              Wyniki miesięczne
            </ModeButton>
          )}
          {hasModule && (
            <ModeButton
              active={visibleView === "archive"}
              onClick={() => changeView("archive")}
            >
              Archiwum
            </ModeButton>
          )}
          {canImportMd && (
            <ModeButton active={view === "md"} onClick={() => changeView("md")}>
              Import zużycia MD
            </ModeButton>
          )}
          <ModeButton
            active={visibleView === "order-changes"}
            onClick={() => changeView("order-changes")}
          >
            Zmiany w zamówieniach
            {todoBadge > 0 ? (
              <span
                className="rounded-full bg-primary px-1.5 text-[11px] font-semibold leading-5 text-primary-foreground tabular-nums"
                aria-label={`${todoBadge} do zrobienia w bieżącym miesiącu`}
              >
                {todoBadge}
              </span>
            ) : null}
          </ModeButton>
          <ModeButton
            active={visibleView === "order-pdfs"}
            onClick={() => changeView("order-pdfs")}
          >
            Zamówienia PDF
          </ModeButton>
          {invoicingOpen ? (
            <ModeButton
              active={visibleView === "sales-invoices"}
              onClick={() => changeView("sales-invoices")}
            >
              Faktury do klientów
            </ModeButton>
          ) : null}
          {hasModule ? (
            <ModeButton
              active={visibleView === "rate-divergences"}
              onClick={() => changeView("rate-divergences")}
              data-tour="finance.rate-divergences"
            >
              Rozjazdy stawek
            </ModeButton>
          ) : null}
          {approvalsOpen ? (
            <ModeButton
              active={visibleView === "approved-expenses"}
              onClick={() => changeView("approved-expenses")}
            >
              Wydatki ze zgodą
            </ModeButton>
          ) : null}
        </div>

        {!mounted ? (
          <div className="py-10 text-center text-sm text-muted-foreground">
            Ładowanie…
          </div>
        ) : visibleView === "results" ? (
          <FinanceResultsTab canWrite={canWrite} />
        ) : visibleView === "archive" ? (
          <FinanceArchiveTab canWrite={canWrite} />
        ) : visibleView === "order-changes" ? (
          <OrderChangesTab onOpenInPdfs={openInPdfs} />
        ) : visibleView === "order-pdfs" ? (
          <OrderPdfsTab />
        ) : visibleView === "sales-invoices" ? (
          <FinanceSalesInvoicesTab />
        ) : visibleView === "rate-divergences" ? (
          <RateDivergencesTab />
        ) : visibleView === "approved-expenses" ? (
          <div data-help="finance.approved-expenses">
            <ApprovedExpensesTab />
          </div>
        ) : (
          <MdImportWorkspace />
        )}
      </div>
    </RequirePermission>
  );
}

function ModeButton({
  active,
  onClick,
  children,
  "data-tour": dataTour,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
  "data-tour"?: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      data-tour={dataTour}
      aria-selected={active}
      onClick={onClick}
      // Podkreślenie jak w `ds/WorkspaceModeTabs` (Klienci, Kontrakty). Zakładki
      // zostają ręczne, bo licznik „do zrobienia" ma własną nazwę dostępną.
      className={cn(
        "-mb-px inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-1.5 text-[13px] transition-colors pointer-coarse:min-h-10",
        active
          ? "border-primary font-semibold text-foreground"
          : "border-transparent font-medium text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}
