"use client";

import { useEffect, useState, type ReactNode } from "react";

import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds";
import { RequireSectionAccess } from "@/components/RequireSectionAccess";
import { FinanceArchiveTab } from "@/components/finance/FinanceArchiveTab";
import { FinanceResultsTab } from "@/components/finance/FinanceResultsTab";
import { MdImportWorkspace } from "@/components/finance/MdImportWorkspace";
import { hasSectionAccess } from "@/lib/section-access";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";

type ViewMode = "results" | "archive" | "md";

/**
 * /finance — moduł „Finanse", trzy powierzchnie pod jedną trasą:
 *
 *  • „Wyniki miesięczne" — koszt / przychód / marża kontraktorów z arkusza,
 *  • „Archiwum"          — historia wgranych plików + przywracanie wersji,
 *  • „Import zużycia MD"  — miesięczne raporty zasilające budżety MD zamówień
 *                           wielo-konsultantowych (PR #1162).
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
    const initial = params.get("view");
    if (initial === "archive" || initial === "md") setView(initial);
    setMounted(true);
  }, []);

  function changeView(next: ViewMode) {
    setView(next);
    const params = new URLSearchParams(window.location.search);
    if (next === "results") {
      params.delete("view");
    } else {
      params.set("view", next);
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
      <div className="mx-auto max-w-[1400px] space-y-4">
        <div
          role="tablist"
          aria-label="Tryb modułu Finanse"
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
        </div>

        <PageHeader
          eyebrow="Finanse · Wyniki kontraktorów"
          title="Finanse"
          description={
            visibleView === "md"
              ? "Miesięczne raporty zużycia MD zasilające budżety zamówień klientów"
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
