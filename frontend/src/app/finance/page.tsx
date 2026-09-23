"use client";

import { Suspense, useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds";
import { RequireSectionAccess } from "@/components/RequireSectionAccess";
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
import { hasSectionAccess } from "@/lib/section-access";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";

import { parseFinanceView, type FinanceViewMode as ViewMode } from "@/lib/finance-view";

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
 * Widoczne dla osób z efektywnym dostępem do sekcji Finance (rola lub wyjątek
 * indywidualny). `RequireSectionAccess` to warstwa UX; realną bramką jest
 * database-backed section guard na backendzie plus podpisany snapshot w
 * `ROLE_ROUTES` (middleware).
 *
 * Stan zakładki żyje w URL przez History API, nie `useSearchParams` — ten drugi
 * wymusza w Next 15 granicę Suspense wokół całej strony (ten sam powód co
 * w /contracts, skąd pochodzi przełącznik).
 */
export default function FinancePage() {
  const user = useAuthStore((state) => state.user);
  const impersonating = useAuthStore((state) => state.realUser !== null);
  const [view, setView] = useState<ViewMode>("results");
  const [mounted, setMounted] = useState(false);
  // Podgląd jako użytkownik jest zawsze read-only, także gdy target ma
  // Finance=write. Backend odrzuca takie mutacje; UI nie może sugerować, że
  // import, restore lub edycja komórek zadziałają.
  const canWrite =
    !impersonating && hasSectionAccess(user, "finance", "write");
  const visibleView = view === "md" && !canWrite ? "results" : view;

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
    const query = params.toString();
    window.history.replaceState(
      null,
      "",
      query ? `${window.location.pathname}?${query}` : window.location.pathname,
    );
  }

  return (
    <RequireSectionAccess
      section="finance"
      fallback={
        <QueryStateNotice
          state="forbidden"
          description="Moduł Finanse wymaga uprawnień finansowych. Poproś administratora o dostęp."
        />
      }
    >
      <Suspense fallback={null}>
        <FinanceViewSync onView={setView} />
      </Suspense>
      <div className="mx-auto max-w-[1400px] space-y-4">
        <div
          role="tablist"
          aria-label="Tryb modułu Finanse"
          data-help="finance.modes"
          className="inline-flex items-center gap-1 rounded-lg border border-[hsl(var(--border))] bg-muted/40 p-1"
        >
          <ModeButton
            active={visibleView === "results"}
            onClick={() => changeView("results")}
          >
            Wyniki miesięczne
          </ModeButton>
          <ModeButton
            active={visibleView === "archive"}
            onClick={() => changeView("archive")}
          >
            Archiwum
          </ModeButton>
          {canWrite && (
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
                className="ml-1.5 inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1.5 text-xs font-semibold text-primary-foreground"
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
        </div>

        <PageHeader
          eyebrow={
            visibleView === "order-changes"
              ? "Finanse · Zmiany w zamówieniach"
              : visibleView === "order-pdfs"
                ? "Finanse · Zamówienia PDF"
                : "Finanse · Wyniki kontraktorów"
          }
          title={
            visibleView === "order-changes"
              ? "Zmiany w zamówieniach"
              : visibleView === "order-pdfs"
                ? "Zamówienia PDF"
                : "Finanse"
          }
          description={
            visibleView === "order-pdfs"
              ? "PDF-y nowych zamówień, przedłużeń i aneksów według miesiąca rozpoczęcia i klienta"
              : visibleView === "md"
              ? "Miesięczne raporty zużycia MD zasilające budżety zamówień klientów"
              : visibleView === "order-changes"
                ? "Bieżący, comiesięczny audyt zdarzeń w zamówieniach na potrzeby rozliczeń"
                : "Miesięczne wyniki finansowe kontraktorów — koszt, przychód i marża"
          }
        />

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
        ) : (
          <MdImportWorkspace />
        )}
      </div>
    </RequireSectionAccess>
  );
}

function ModeButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
        active
          ? "bg-background text-foreground shadow-xs"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}
