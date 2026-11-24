"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { QueryStateNotice } from "@/components/ds";
import { RequirePermission } from "@/components/RequirePermission";
import { FinanceArchiveTab } from "@/components/finance/FinanceArchiveTab";
import { FinanceResultsTab } from "@/components/finance/FinanceResultsTab";
import { MdImportWorkspace } from "@/components/finance/MdImportWorkspace";
import {
  ORDER_CHANGES_URL_KEYS,
  OrderChangesTab,
} from "@/components/finance/OrderChangesTab";
import {
  ORDER_PDFS_URL_KEYS,
  OrderPdfsTab,
} from "@/components/finance/OrderPdfsTab";
import type { OrderPdfRef } from "@/lib/api/finance";
import { hasPermission } from "@/lib/permissions";
import { hasSectionAccess } from "@/lib/section-access";
import { useAuthStore } from "@/store/auth";

import { parseFinanceView, type FinanceViewMode as ViewMode } from "@/lib/finance-view";
import {
  FinanceSalesInvoicesTab,
  type SalesInvoicesView,
} from "@/components/clients/invoicing/FinanceSalesInvoicesTab";
import { RateDivergencesTab } from "@/components/finance/RateDivergencesTab";
import { MONTH_CLOSE_URL_KEYS, MonthCloseView } from "@/components/finance/month-close/MonthCloseView";
import { SETTLEMENTS_URL_KEYS, SettlementsTab } from "@/components/finance/settlements/SettlementsTab";
import { useInvoicingModule } from "@/lib/api/client-invoicing";
import { useSettlementsModule } from "@/lib/api/client-settlements";
import {
  APPROVED_EXPENSES_URL_KEYS,
  ApprovedExpensesTab,
} from "@/components/finance/ApprovedExpensesTab";
import { useHrConfig } from "@/lib/api/hr";
import { COSTS_URL_KEYS, CostsTab } from "@/components/finance/ledger/CostsTab";
import { BookingTab } from "@/components/finance/ledger/BookingTab";
import { ChartTab } from "@/components/finance/ledger/ChartTab";
import { CounterpartiesTab } from "@/components/finance/ledger/CounterpartiesTab";
import { PaymentsTab } from "@/components/finance/ledger/PaymentsTab";
import { Ebi24ArchiveTab } from "@/components/finance/ledger/Ebi24ArchiveTab";
import { useAccountingModule } from "@/lib/api/finance-ledger";
import { useLedgerConfig } from "@/lib/api/accounting";
import { FinanceAreaNav, financeItemKey } from "@/components/finance/FinanceAreaNav";

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
    "Faktury do klientów: wystawianie do KSeF, dopasowanie do zamówień, wpłaty z wyciągu i zaległości",
  "rate-divergences":
    "Zamówienia do korekty po zmianie stawki Partnera i nocny raport rozjazdów linii zamówień MD",
  settlements: "RCP, faktury kontraktorów i faktury do klienta za jeden miesiąc",
  "month-close": "Kontraktorzy, biuro i klienci w jednym miesiącu: automat, błędy, braki i faktury",
  "approved-expenses":
    "Zatwierdzone wydatki do rozliczenia, rejestr subskrypcji i faktury kosztowe bez zgody",
  costs:
    "Faktury kosztowe z KSeF i PDF w jednej kolejce: przyjęcie, opis, weryfikacja, księgowanie",
  counterparties: "Kartoteka kontrahentów z kontami Symfonii, import z eBI24",
  payments:
    "Paczki przelewów faktur kosztowych (Elixir-O, CSV, MPP) i zapłaty z wyciągu",
  booking: "Dekrety faktur gotowych do księgowania za miesiąc i paczki eksportu do Symfonii FK",
  accounts: "Plan kont Symfonii FK i reguły dekretu faktur kosztowych",
  "ebi24-archive":
    "Dokumenty z archiwum eBI24 (2021–2026): faktury sprzedaży i kosztowe z plikami",
};

/**
 * FE-N09 (audyt 22.09 r2): widok idzie za `?view=` także przy MIĘKKIEJ
 * nawigacji — link (np. z powiadomienia) do `/finance?view=order-changes`
 * przy otwartym module nie odmontowuje strony, więc odczyt `window.location`
 * przy montowaniu go nie widział. Efekt zależy od WARTOŚCI parametru; mały
 * komponent w `Suspense`, żeby `useSearchParams` nie wymusił granicy
 * Suspense wokół całej strony.
 */
/** Wejście do „Faktur do klientów” z miesiącem i widokiem (link „Wystaw” z „Przebiegu miesiąca”). */
const SALES_INVOICES_URL_KEYS = ["siPeriod", "siView", "siClient"] as const;
// „issue-settings”: dzwonek CPro o nieznanym kodzie adresu prowadzi do „Kod w CPro” nabywcy.
const SALES_INVOICES_LINK_VIEWS: readonly SalesInvoicesView[] = ["issue", "to-invoice", "invoices", "issue-settings"];

function salesInvoicesFromUrl(): { initialPeriod?: string; initialView?: SalesInvoicesView; initialClientId?: number } {
  if (typeof window === "undefined") return {};
  const params = new URLSearchParams(window.location.search);
  const period = params.get("siPeriod");
  const view = params.get("siView") as SalesInvoicesView | null;
  const client = Number(params.get("siClient"));
  return {
    initialClientId: Number.isInteger(client) && client > 0 ? client : undefined,
    initialPeriod: period && /^\d{4}-\d{2}$/.test(period) ? period : undefined,
    initialView: view && SALES_INVOICES_LINK_VIEWS.includes(view) ? view : undefined,
  };
}

function FinanceViewSync({ onView }: { onView: (raw: string | null) => void }) {
  const searchParams = useSearchParams();
  const raw = searchParams ? searchParams.get("view") : undefined;
  useEffect(() => {
    // `undefined` = poza routerem App (testy) — zostaje odczyt przy montowaniu.
    if (raw === undefined) return;
    onView(raw);
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
  const router = useRouter();
  const [view, setView] = useState<ViewMode>("results");
  const hasModule = hasPermission(user, "finance_module");
  const [mounted, setMounted] = useState(false);
  // Samo `/finance` (bez `?view=`) to wejście do modułu (makieta 18.11.2026):
  // przy otwartej Księdze prowadzi na Przegląd miesiąca (`/accounting`).
  const [viewInAddress, setViewInAddress] = useState(true);
  const ledger = useLedgerConfig(hasModule);
  const landOnOverview = mounted && !viewInAddress && ledger.data?.open === true;
  const waitingForLanding = mounted && !viewInAddress && hasModule && ledger.isLoading;
  const syncView = useCallback((raw: string | null) => {
    setViewInAddress(raw !== null);
    setView(parseFinanceView(raw));
  }, []);
  useEffect(() => {
    if (landOnOverview) router.replace("/accounting");
  }, [landOnOverview, router]);
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
  // „Rozliczenia” (rozliczenia klientów, roadmapa E1) tylko przy włączonym module.
  const settlementsOpen = useSettlementsModule(hasModule).data?.open === true;
  // „Koszty” i „Kontrahenci” (księgowość E0–E1) tylko przy włączonym module.
  const accountingOpen = useAccountingModule(hasModule).data?.open === true;
  // Import MD: `orders_work`, nie zapis sekcji — sekcji Back office nie ma.
  const canImportMd = !impersonating && hasPermission(user, "orders_work");
  const fallbackView: ViewMode = hasModule ? "results" : "order-changes";
  const visibleView =
    (view === "md" && !canImportMd) ||
    (view === "results" && !hasModule) ||
    (view === "archive" && !hasModule) ||
    (view === "sales-invoices" && !invoicingOpen) ||
    (view === "rate-divergences" && !hasModule) ||
    (view === "approved-expenses" && !approvalsOpen) ||
    (view === "settlements" && !settlementsOpen) ||
    (view === "month-close" && !settlementsOpen) ||
    ((view === "costs" ||
      view === "counterparties" ||
      view === "payments" ||
      view === "booking" ||
      view === "accounts" ||
      view === "ebi24-archive") &&
      !accountingOpen)
      ? fallbackView
      : view;

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    syncView(params.get("view"));
    setMounted(true);
  }, [syncView]);


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
    // Zawsze z `?view=` — samo `/finance` prowadzi na Przegląd miesiąca.
    params.set("view", next);
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
    if (next !== "settlements") {
      SETTLEMENTS_URL_KEYS.forEach((key) => params.delete(key));
    }
    if (next !== "month-close") {
      MONTH_CLOSE_URL_KEYS.forEach((key) => params.delete(key));
    }
    if (next !== "sales-invoices") {
      SALES_INVOICES_URL_KEYS.forEach((key) => params.delete(key));
    }
    if (next !== "costs") {
      COSTS_URL_KEYS.forEach((key) => params.delete(key));
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
        <FinanceViewSync onView={syncView} />
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

        {/* Makieta 18.11.2026: Finanse i Księga w jednej nawigacji w grupach
            (`FinanceAreaNav`) zamiast 15 zakładek w jednym rzędzie. */}
        <FinanceAreaNav active={financeItemKey(visibleView)} />

        {!mounted || waitingForLanding || landOnOverview ? (
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
          <FinanceSalesInvoicesTab {...salesInvoicesFromUrl()} />
        ) : visibleView === "rate-divergences" ? (
          <RateDivergencesTab
            canWrite={!impersonating && hasPermission(user, "amounts_edit")}
          />
        ) : visibleView === "settlements" ? (
          <SettlementsTab canWrite={canWrite} />
        ) : visibleView === "month-close" ? (
          <MonthCloseView />
        ) : visibleView === "costs" ? (
          <CostsTab canWrite={canWrite} />
        ) : visibleView === "counterparties" ? (
          <CounterpartiesTab canWrite={canWrite} />
        ) : visibleView === "ebi24-archive" ? (
          <Ebi24ArchiveTab />
        ) : visibleView === "payments" ? (
          <PaymentsTab canWrite={canWrite} />
        ) : visibleView === "booking" ? (
          <BookingTab canWrite={canWrite} />
        ) : visibleView === "accounts" ? (
          <ChartTab canWrite={canWrite} />
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
