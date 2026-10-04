"use client";

import type { ReactNode } from "react";
import {
  ArrowLeft,
  BookOpen,
  Building2,
  ClipboardList,
  Columns3,
  Copy,
  Ellipsis,
  FileText,
  FileUp,
  House,
  Link2,
  MessageCircle,
  PencilLine,
  RotateCcw,
  ScanSearch,
  Send,
  Sparkles,
  Trophy,
  UserPlus,
  Users,
  Wallet,
  Wand2,
  XCircle,
  type LucideIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { JobDetailView } from "@/lib/job-detail-routing";
import type { JobHeaderFact, JobHeaderFactKey } from "@/lib/job-header-facts";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

/**
 * DAWNE identyfikatory zakładek rekrutacji (do wersji 3 — dwanaście kroków na
 * listwie). Widoków jest dziś trzy (`JobDetailView`), ale ten typ zostaje:
 * warsztaty (`ScreeningWorkbench`, `SourcingHub`) i KPI nagłówka nadal mówią
 * tym słownikiem, a strona tłumaczy go przez `resolveLegacyJobTab`.
 */
export type JobDetailTab =
  | "pipeline"
  | "history"
  | "ai-matching"
  | "manual-search"
  | "portals"
  | "champion"
  | "questions"
  | "chat"
  // Kroki 05 i 06 programu „flow w języku C2" (PR 6/7) — NOWE wartości,
  // żadna istniejąca nie jest przepinana (kontrakt wspólny programu).
  | "screening"
  | "cv"
  // Kroki 07 i 08 programu „flow w języku C2" (PR 7/7). Dochodzą jako NOWE
  // wartości — żadna istniejąca zakładka nie jest przepinana.
  | "interviews"
  | "contract";

interface JobDetailCompactHeaderProps {
  /** Tytuł stanowiska (tytuł dla rekrutera, a bez niego nazwa od klienta). */
  title: string;
  /**
   * 0380: nazwa od klienta (gdy tytuł w nagłówku to tytuł dla rekrutera)
   * i numer u klienta — to, co idzie do klienta w CV i do Cpro.
   */
  clientTitle?: string | null;
  clientReference?: string | null;
  /** Nasz numer rekrutacji. */
  referenceNumber?: string | null;
  /** Status requestu („Szukamy”), „Tylko odczyt”, plakietki Traffita. */
  badges?: ReactNode;
  /** Klient · Budżet · Tryb pracy (`lib/job-header-facts.ts`). */
  facts: readonly JobHeaderFact[];
  presence?: ReactNode;
  /** Aktywny widok: „Tablica" albo „Profil Championa" (`people` = lista „Do przejrzenia"). */
  activeView: JobDetailView;
  onViewChange: (view: JobDetailView) => void;
  /**
   * Ile rzeczy brakuje w zleceniu wg bramki gotowości. `undefined`/`null` =
   * nie wiadomo (rola spoza bramki, zapytanie w toku) — odznaki nie ma;
   * zero też jej nie pokazuje („brakuje 0" to szum).
   */
  orderMissingCount?: number | null;
  onOpenHistoryChat: () => void;
  chatUnreadCount?: number;

  // ── Menu „⋯" — wszystko, co zeszło z widoku, żyje tutaj ─────────────────
  onOpenQuestions: () => void;
  /** Okno „Zlecenie” — skrót: braki, fakty, wymagania. */
  onOpenOrder: () => void;
  /**
   * „Zespół” — kto pracuje nad rekrutacją („Rekruter: Marta N. +1” albo
   * „Bez rekrutera”); klik otwiera zakładkę „Zespół i ogłoszenie” Profilu
   * Championa.
   * Do 02.10.2026 ta informacja stała w podtytule nagłówka.
   */
  teamSummary?: string | null;
  onOpenTeam?: () => void;
  /**
   * „Edytuj cały Profil Championa” (04.10.2026): pełny formularz z „Wypełnij
   * szybciej”. Na co dzień edycja idzie blokami z Briefu. `undefined` = rola
   * bez edycji Championa (brak pozycji).
   */
  onEditFullChampion?: () => void;
  /**
   * „Mamy championa" (0341) — przełącznik Delivery Leada. `undefined` = rola
   * bez prawa (brak pozycji); status widać wtedy w odznace statusu.
   */
  championFound?: boolean;
  onToggleChampion?: () => void;
  championPending?: boolean;
  /** „Dodaj po nazwisku” / „Dodaj z pliku CV” — brak = rola bez prawa dodawania. */
  onAddByName?: () => void;
  onAddFromCv?: () => void;
  /** Ręczny przegląd całej bazy przez AI (ok. 3 minut) — wyniki w „Propozycjach z bazy”. */
  onStartFullReview?: () => void;
  /**
   * „Moi ludzie do tej rekrutacji” — otwiera panel „Moi ludzie” (na stronie
   * rekrutacji startuje na zakładce tej rekrutacji). Do 02.10.2026 zakładka
   * okna „Dodaj kandydatów”.
   */
  onOpenMyPeople?: () => void;
  /** „Ukryj / pokaż puste kolumny” Tablicy; `undefined` poza Tablicą. */
  emptyColumnsHidden?: boolean;
  onToggleEmptyColumns?: () => void;
  onEdit?: () => void;
  onWriteAnnouncement?: () => void;
  onGenerateInviteLink?: () => void;
  /**
   * Narzędzia AI administratora (kryteria, scoring, embedding). Strona podaje
   * je WYŁĄCZNIE adminowi.
   */
  onOpenAiTools?: () => void;
  /** „Karta klienta” (link do Pomocy). Brak = rekrutacja bez klienta. */
  clientCardHref?: string;
  onCopyLink?: () => void;
  /** „Zamknij rekrutację…” — pełna edycja i rekrutacja nie zamknięta. */
  onCloseJob?: () => void;
  /**
   * „Otwórz ponownie…” — zamknięta rekrutacja, ta sama bramka co zamknięcie
   * (04.10.2026). Otwiera `JobReopenDialog`; zmiana statusu w edycji już tego
   * nie robi.
   */
  onReopenJob?: () => void;
  /** „Dokończ i opublikuj…” — stary szkic albo rekrutacja bez przekazania. */
  onFinishJob?: () => void;
}

function deferMenuAction(action: () => void) {
  window.setTimeout(action, 0);
}

const FACT_ICON: Record<JobHeaderFactKey, LucideIcon> = {
  client: Building2,
  budget: Wallet,
  work_mode: House,
};

/**
 * Nagłówek rekrutacji (02.10.2026, makieta B:
 * https://claude.ai/artifact/ASHNaTXA9omvTH393cQjCv).
 *
 * Decyzja Artura: na górze tylko tytuł stanowiska, pod nim tytuł od klienta
 * i trzy wyróżnione fakty — klient, budżet, tryb pracy. Zniknęły liczniki
 * („W procesie”, „Utknęli”, „U klienta”), ścieżka „Zlecenie → … → Umowa”
 * z „Najbliższym krokiem” i przyciski „Dodaj kandydatów”, „Podobne
 * rekrutacje”, „Oznacz: mamy championa”. Żadna funkcja nie znika: to, co
 * zeszło z widoku, jest w menu „⋯” (albo na kaflach „Kandydaci do dodania”).
 */
export function JobDetailCompactHeader({
  title,
  clientTitle,
  clientReference,
  referenceNumber,
  badges,
  facts,
  presence,
  activeView,
  onViewChange,
  orderMissingCount,
  onOpenHistoryChat,
  chatUnreadCount = 0,
  onOpenQuestions,
  onOpenOrder,
  teamSummary,
  onOpenTeam,
  onEditFullChampion,
  championFound,
  onToggleChampion,
  championPending,
  onAddByName,
  onAddFromCv,
  onStartFullReview,
  onOpenMyPeople,
  emptyColumnsHidden,
  onToggleEmptyColumns,
  onEdit,
  onWriteAnnouncement,
  onGenerateInviteLink,
  onOpenAiTools,
  clientCardHref,
  onCopyLink,
  onCloseJob,
  onReopenJob,
  onFinishJob,
}: JobDetailCompactHeaderProps) {
  const unreadLabel =
    chatUnreadCount > 0
      ? `Historia i czat, ${chatUnreadCount > 99 ? "ponad 99" : chatUnreadCount} nieprzeczytane`
      : "Historia i czat";
  const missing =
    typeof orderMissingCount === "number" && orderMissingCount > 0
      ? orderMissingCount
      : null;
  const clientLine = [
    clientTitle ? `U klienta: „${clientTitle}”` : null,
    clientReference ? `nr u klienta ${clientReference}` : null,
    referenceNumber ? `nasz nr ${referenceNumber}` : null,
  ].filter(Boolean);
  const hasAdding = Boolean(onAddByName || onAddFromCv || onStartFullReview || onOpenMyPeople);

  return (
    <header className="space-y-2 rounded-lg border border-border bg-card px-4 py-3">
      {/* `flex-wrap`: na laptopie 1280 px zakładki i przyciski schodzą pod
          tytuł, zamiast go ucinać. */}
      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
        <div className="min-w-0 flex-[1_1_22rem]">
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <h1
              className="min-w-0 text-xl font-semibold leading-tight text-foreground line-clamp-2"
              title={title}
            >
              {title}
            </h1>
            {badges}
          </div>
          {clientLine.length > 0 ? (
            <p
              className="mt-1 line-clamp-2 text-[13px] text-muted-foreground"
              data-testid="header-client-line"
              title={clientLine.join(" · ")}
            >
              {clientTitle ? (
                <span data-testid="header-client-title">U klienta: „{clientTitle}”</span>
              ) : null}
              {clientReference ? (
                <span data-testid="header-client-reference">
                  {clientTitle ? " · " : ""}nr u klienta {clientReference}
                </span>
              ) : null}
              {referenceNumber ? (
                <span>
                  {clientTitle || clientReference ? " · " : ""}nasz nr {referenceNumber}
                </span>
              ) : null}
            </p>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Dwa widoki rekrutacji jako zakładki. Pełna lista „Do przejrzenia”
              (`tab=people`) nie jest zakładką — z niej wraca „Tablica”. */}
          <nav
            className="flex shrink-0 items-center gap-0.5 rounded-lg bg-muted p-0.5"
            aria-label="Widok rekrutacji"
          >
            <button
              type="button"
              onClick={() => onViewChange("board")}
              aria-current={activeView === "board" ? "page" : undefined}
              data-testid="view-board"
              className={cn(
                "inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-[13px] font-medium transition-colors",
                activeView === "board"
                  ? "bg-card text-primary shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {activeView !== "board" && activeView !== "champion" ? (
                <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
              ) : null}
              Tablica
            </button>
            <button
              type="button"
              onClick={() => onViewChange("champion")}
              aria-current={activeView === "champion" ? "page" : undefined}
              data-testid="open-champion-profile"
              className={cn(
                "inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-[13px] font-medium transition-colors",
                activeView === "champion"
                  ? "bg-card text-primary shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <FileText className="h-3.5 w-3.5" aria-hidden="true" />
              Profil Championa
              {missing != null ? (
                <Badge variant="warning" size="sm" className="tabular-nums">
                  brakuje {missing}
                </Badge>
              ) : null}
            </button>
          </nav>

          {presence}

          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={onOpenHistoryChat}
            aria-label={unreadLabel}
            data-testid="open-history-chat"
          >
            <MessageCircle className="h-4 w-4" aria-hidden="true" />
            Historia i czat
            {chatUnreadCount > 0 ? (
              <Badge variant="danger" size="sm" className="tabular-nums" aria-hidden="true">
                {chatUnreadCount > 99 ? "99+" : chatUnreadCount}
              </Badge>
            ) : null}
          </Button>

          <DropdownMenu modal={false}>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                size="icon-sm"
                variant="outline"
                aria-label="Więcej akcji rekrutacji"
                title="Więcej akcji"
                data-help="job.champion.found"
              >
                <Ellipsis className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-64">
              {onFinishJob || onReopenJob ? (
                <>
                  {onFinishJob ? (
                    <DropdownMenuItem
                      onSelect={() => deferMenuAction(onFinishJob)}
                      data-testid="finish-job"
                    >
                      <Send className="h-4 w-4" />
                      Dokończ i opublikuj…
                    </DropdownMenuItem>
                  ) : null}
                  {onReopenJob ? (
                    <DropdownMenuItem
                      onSelect={() => deferMenuAction(onReopenJob)}
                      data-testid="reopen-job"
                    >
                      <RotateCcw className="h-4 w-4" />
                      Otwórz ponownie…
                    </DropdownMenuItem>
                  ) : null}
                  <DropdownMenuSeparator />
                </>
              ) : null}

              {onToggleChampion ? (
                <>
                  <DropdownMenuItem
                    onSelect={() => deferMenuAction(onToggleChampion)}
                    disabled={championPending}
                    data-testid="toggle-champion"
                    title={
                      championFound
                        ? "Cofnij „Mamy championa” — rekrutacja wraca do „Szukamy”"
                        : "Mamy championa — dalej nie szukamy"
                    }
                  >
                    <Trophy className="h-4 w-4" />
                    {championFound ? "Cofnij „Mamy championa”" : "Oznacz: mamy championa"}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                </>
              ) : null}

              {hasAdding ? (
                <>
                  <DropdownMenuLabel>Kandydaci</DropdownMenuLabel>
                  {onAddByName ? (
                    <DropdownMenuItem
                      onSelect={() => deferMenuAction(onAddByName)}
                      data-testid="menu-add-by-name"
                    >
                      <UserPlus className="h-4 w-4" />
                      Dodaj po nazwisku
                    </DropdownMenuItem>
                  ) : null}
                  {onAddFromCv ? (
                    <DropdownMenuItem
                      onSelect={() => deferMenuAction(onAddFromCv)}
                      data-testid="menu-add-from-cv"
                    >
                      <FileUp className="h-4 w-4" />
                      Dodaj z pliku CV
                    </DropdownMenuItem>
                  ) : null}
                  {onStartFullReview ? (
                    <DropdownMenuItem
                      onSelect={() => deferMenuAction(onStartFullReview)}
                      data-testid="menu-full-review"
                      title="AI przegląda całą bazę pod tę rekrutację — ok. 3 minut. Wyniki trafią do „Propozycji z bazy”."
                    >
                      <ScanSearch className="h-4 w-4" />
                      Przeszukaj całą bazę (AI)
                    </DropdownMenuItem>
                  ) : null}
                  {onOpenMyPeople ? (
                    <DropdownMenuItem
                      onSelect={() => deferMenuAction(onOpenMyPeople)}
                      data-testid="menu-my-people"
                    >
                      <Users className="h-4 w-4" />
                      Moi ludzie do tej rekrutacji
                    </DropdownMenuItem>
                  ) : null}
                  <DropdownMenuSeparator />
                </>
              ) : null}

              <DropdownMenuLabel>Rekrutacja</DropdownMenuLabel>
              <DropdownMenuItem
                onSelect={() => deferMenuAction(onOpenOrder)}
                data-testid="open-order"
              >
                <ClipboardList className="h-4 w-4" />
                Zlecenie — skrót
              </DropdownMenuItem>
              {onEditFullChampion ? (
                <DropdownMenuItem
                  onSelect={() => deferMenuAction(onEditFullChampion)}
                  data-testid="menu-edit-full-champion"
                >
                  <PencilLine className="h-4 w-4" />
                  Edytuj cały Profil Championa
                </DropdownMenuItem>
              ) : null}
              {onOpenTeam ? (
                <DropdownMenuItem
                  onSelect={() => deferMenuAction(onOpenTeam)}
                  data-testid="menu-team"
                >
                  <Users className="h-4 w-4" />
                  <span className="min-w-0">
                    Zespół
                    {teamSummary ? (
                      <span className="block truncate text-xs text-muted-foreground">
                        {teamSummary}
                      </span>
                    ) : null}
                  </span>
                </DropdownMenuItem>
              ) : null}
              <DropdownMenuItem
                onSelect={() => deferMenuAction(onOpenQuestions)}
                data-testid="open-questions"
              >
                <BookOpen className="h-4 w-4" />
                Baza pytań
              </DropdownMenuItem>
              {onEdit ? (
                <DropdownMenuItem onSelect={() => deferMenuAction(onEdit)}>
                  <PencilLine className="h-4 w-4" />
                  Edytuj
                </DropdownMenuItem>
              ) : null}
              {onWriteAnnouncement ? (
                <DropdownMenuItem onSelect={() => deferMenuAction(onWriteAnnouncement)}>
                  <Wand2 className="h-4 w-4" />
                  Szkic ogłoszenia
                </DropdownMenuItem>
              ) : null}
              {onGenerateInviteLink ? (
                <DropdownMenuItem onSelect={() => deferMenuAction(onGenerateInviteLink)}>
                  <Link2 className="h-4 w-4" />
                  Wygeneruj link
                </DropdownMenuItem>
              ) : null}
              {clientCardHref ? (
                <DropdownMenuItem asChild>
                  <a href={clientCardHref} data-testid="open-client-card">
                    <Building2 className="h-4 w-4" />
                    Karta klienta
                  </a>
                </DropdownMenuItem>
              ) : null}
              {onCopyLink ? (
                <DropdownMenuItem
                  onSelect={() => deferMenuAction(onCopyLink)}
                  data-testid="copy-job-link"
                >
                  <Copy className="h-4 w-4" />
                  Kopiuj link do rekrutacji
                </DropdownMenuItem>
              ) : null}
              {onToggleEmptyColumns ? (
                <DropdownMenuItem
                  onSelect={() => deferMenuAction(onToggleEmptyColumns)}
                  data-testid="toggle-empty-columns"
                >
                  <Columns3 className="h-4 w-4" />
                  {emptyColumnsHidden ? "Pokaż puste kolumny" : "Ukryj puste kolumny"}
                </DropdownMenuItem>
              ) : null}
              {onOpenAiTools ? (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onSelect={() => deferMenuAction(onOpenAiTools)}
                    data-testid="open-ai-tools"
                  >
                    <Sparkles className="h-4 w-4" />
                    Narzędzia AI (administrator)
                  </DropdownMenuItem>
                </>
              ) : null}
              {onCloseJob ? (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onSelect={() => deferMenuAction(onCloseJob)}
                    className="text-destructive focus:text-destructive"
                    data-testid="close-job"
                  >
                    <XCircle className="h-4 w-4" />
                    Zamknij rekrutację…
                  </DropdownMenuItem>
                </>
              ) : null}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Klient · Budżet · Tryb pracy — trzy rzeczy, które rekruter sprawdza
          przed każdym telefonem. Brak wartości to „nie podano”, nie pustka. */}
      <dl className="flex flex-wrap gap-2" data-testid="job-header-facts">
        {facts.map((fact) => {
          const Icon = FACT_ICON[fact.key];
          return (
            <div
              key={fact.key}
              className="flex min-w-0 items-center gap-2.5 rounded-lg border border-primary/20 bg-primary/5 py-1.5 pl-2 pr-3.5"
              data-testid={`job-header-fact-${fact.key}`}
            >
              <span
                aria-hidden="true"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-card text-primary"
              >
                <Icon className="h-4 w-4" />
              </span>
              <div className="min-w-0">
                <dt className="text-[11px] font-semibold uppercase tracking-eyebrow text-muted-foreground">
                  {fact.label}
                </dt>
                <dd
                  className={cn(
                    "truncate text-[15px] font-semibold leading-tight",
                    fact.value ? "text-foreground" : "font-normal text-muted-foreground",
                  )}
                  title={fact.value ?? undefined}
                >
                  {fact.value ?? "nie podano"}
                </dd>
              </div>
            </div>
          );
        })}
      </dl>
    </header>
  );
}
