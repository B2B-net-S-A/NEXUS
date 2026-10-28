"use client";

import type { MouseEvent, ReactNode } from "react";
import {
  ArrowLeft,
  Paperclip,
  Building2,
  ChevronDown,
  ChevronUp,
  ClipboardList,
  Copy,
  Ellipsis,
  FileText,
  FileUp,
  Link2,
  MapPin,
  Megaphone,
  MessageCircle,
  PencilLine,
  RotateCcw,
  ScanSearch,
  Send,
  Sparkles,
  UserPlus,
  Users,
  Wallet,
  XCircle,
  type LucideIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ClientReferenceChip } from "@/components/v2/jobs/ClientReferenceChip";
import type { JobDetailView } from "@/lib/job-detail-routing";
import { isPlainLeftClick } from "@/lib/plain-left-click";
import type { JobHeaderFact, JobHeaderFactKey } from "@/lib/job-header-facts";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
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

/** Strona kariery i portale, na których wisi ogłoszenie rekrutacji. */
export interface AdChannelDots {
  career: boolean;
  pracuj: boolean;
  jjit: boolean;
}

const AD_CHANNEL_LABELS: ReadonlyArray<{ key: keyof AdChannelDots; label: string }> = [
  { key: "career", label: "strona kariery" },
  { key: "pracuj", label: "Pracuj.pl" },
  { key: "jjit", label: "JustJoin.IT" },
];

function adButtonLabel(channels: AdChannelDots | null): string {
  if (!channels) return "Ogłoszenie";
  const live = AD_CHANNEL_LABELS.filter(({ key }) => channels[key]).map(({ label }) => label);
  return live.length > 0
    ? `Ogłoszenie — wisi: ${live.join(", ")}`
    : "Ogłoszenie — jeszcze nigdzie nie wisi";
}

interface JobDetailCompactHeaderProps {
  /** Tytuł stanowiska (tytuł dla rekrutera, a bez niego nazwa od klienta). */
  title: string;
  /**
   * 0380: nazwa od klienta (gdy tytuł w nagłówku to tytuł dla rekrutera)
   * i numer u klienta — to, co idzie do klienta w CV i do Cpro.
   */
  clientTitle?: string | null;
  clientReference?: string | null;
  /** Klik w numer u klienta przed tytułem (15.10.2026) — kopiuje go. */
  onCopyClientReference?: (reference: string) => void;
  /** Nasz numer rekrutacji. */
  referenceNumber?: string | null;
  /** Status requestu („Szukamy”), „Tylko odczyt”, plakietki Traffita. */
  badges?: ReactNode;
  /** Klient · Budżet · Tryb pracy (`lib/job-header-facts.ts`). */
  facts: readonly JobHeaderFact[];
  /** Plakietka priorytetu przed tytułem (`JobPriorityMenu`, 14.10.2026). */
  priority?: ReactNode;
  /** Pasek P0 nad tytułem (`JobP0Strip`, 27.10.2026) — tylko gdy P0 trwa. */
  p0Strip?: ReactNode;
  /** Czwarty fakt „Rekruter” (`JobRecruiterFact`). */
  recruiter?: ReactNode;
  /** Ten sam fakt w zwiniętym nagłówku — same awatary, w linii tytułu. */
  recruiterCompact?: ReactNode;
  /**
   * Trzecia linia, tylko na Tablicy: „Kandydaci do dodania”
   * (`CandidateSourcesStrip`) — do 14.10.2026 osobny pasek nad Tablicą.
   */
  sources?: ReactNode;
  /** Po prawej w linii źródeł — filtr Tablicy „Kto dodał”. */
  sourcesTrailing?: ReactNode;
  /**
   * Nagłówek zwinięty do linii tytułu (K-D5). `onToggleCollapsed` brak = bez
   * przycisku „Zwiń”.
   */
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
  /** W zwiniętym nagłówku: włączony filtr „Kto dodał”, żeby nie był ukryty. */
  collapsedExtras?: ReactNode;
  presence?: ReactNode;
  /** Aktywny widok: „Tablica" albo „Profil Championa" (`people` = lista „Do przejrzenia"). */
  activeView: JobDetailView;
  onViewChange: (view: JobDetailView) => void;
  /**
   * Adres widoku. Podany = zakładki są linkami: środkowy przycisk i Ctrl/Cmd+klik
   * otwierają widok w nowej karcie, zwykły klik dalej przełącza w miejscu.
   */
  viewHref?: (view: JobDetailView) => string;
  /**
   * Ile rzeczy brakuje w zleceniu wg bramki gotowości. `undefined`/`null` =
   * nie wiadomo (rola spoza bramki, zapytanie w toku) — odznaki nie ma;
   * zero też jej nie pokazuje („brakuje 0" to szum).
   */
  orderMissingCount?: number | null;
  onOpenHistoryChat: () => void;
  chatUnreadCount?: number;

  // ── Menu „⋯" — 9 pozycji (decyzja Artura 25.10.2026) ────────────────────
  /** Okno „Pliki” — request klienta i załączniki rekrutacji (0428). */
  onOpenFiles?: () => void;
  /** Liczba plików; `undefined` = jeszcze nie wiadomo (bez liczby w menu). */
  filesCount?: number;
  /** Okno „Zlecenie” — skrót: braki, fakty, wymagania. */
  onOpenOrder: () => void;
  /**
   * „Edytuj Profil Championa” (04.10.2026): pełny formularz z „Wypełnij
   * szybciej”. Na co dzień edycja idzie blokami z Briefu. `undefined` = rola
   * bez edycji Championa (brak pozycji).
   */
  onEditFullChampion?: () => void;
  /** Podmenu „Dodaj kandydatów”: po nazwisku / z pliku CV — brak = rola bez prawa dodawania. */
  onAddByName?: () => void;
  onAddFromCv?: () => void;
  /** Ręczny przegląd całej bazy przez AI (ok. 3 minut) — wyniki w „Propozycjach z bazy”. */
  onStartFullReview?: () => void;
  /**
   * „Z moich ludzi” — otwiera panel „Moi ludzie” (na stronie rekrutacji
   * startuje na zakładce tej rekrutacji). Do 02.10.2026 zakładka okna „Dodaj
   * kandydatów”.
   */
  onOpenMyPeople?: () => void;
  /** „Edytuj dane rekrutacji” — okno z opisem, wymaganiami i danymi firmy. */
  onEdit?: () => void;
  /**
   * Okno „Ogłoszenie” — od 21.10.2026 przycisk w nagłówku z kropkami: gdzie
   * ogłoszenie wisi. Od 25.10.2026 już nie także w menu „⋯”.
   */
  onWriteAnnouncement?: () => void;
  /** Gdzie ogłoszenie wisi — kropki przy „Ogłoszenie”. Brak = bez kropek. */
  adChannels?: AdChannelDots | null;
  /** „Link do zgłoszeń kandydatów” — link, przez który kandydat sam się zgłasza. */
  onGenerateInviteLink?: () => void;
  /**
   * Narzędzia AI administratora (kryteria, scoring, embedding). Strona podaje
   * je WYŁĄCZNIE adminowi.
   */
  onOpenAiTools?: () => void;
  onCopyLink?: () => void;
  /** „Zamknij rekrutację…” — pełna edycja i rekrutacja nie zamknięta. */
  onCloseJob?: () => void;
  /**
   * „Otwórz ponownie…” — zamknięta rekrutacja, ta sama bramka co zamknięcie
   * (04.10.2026). Otwiera `JobReopenDialog`; zmiana statusu w edycji już tego
   * nie robi.
   */
  onReopenJob?: () => void;
  /** „Zmień powód zamknięcia…” — zamknięta rekrutacja (21.10.2026). */
  onChangeCloseReason?: () => void;
  /** „Dokończ i opublikuj…” — stary szkic albo rekrutacja bez przekazania. */
  onFinishJob?: () => void;
}

/** Ikona faktu zamiast etykiety (K-D2, 14.10.2026) — etykieta w dymku. */
const FACT_ICON: Record<JobHeaderFactKey, LucideIcon> = {
  client: Building2,
  budget: Wallet,
  work_mode: MapPin,
};

/**
 * Kto ustępuje, gdy linia faktów jest za ciasna (laptop 1280 px z menu):
 * najpierw nazwa klienta (najwyżej 15rem), potem tryb pracy; budżet nigdy.
 */
const FACT_SHRINK: Record<JobHeaderFactKey, string> = {
  client: "max-w-60 shrink-[4]",
  budget: "shrink-0",
  work_mode: "shrink",
};

function deferMenuAction(action: () => void) {
  window.setTimeout(action, 0);
}

interface ViewTabProps {
  view: JobDetailView;
  activeView: JobDetailView;
  onViewChange: (view: JobDetailView) => void;
  href?: string;
  testId: string;
  children: ReactNode;
}

/**
 * Zakładka widoku. Z adresem to link (21.10.2026): środkowy przycisk
 * i Ctrl/Cmd+klik zostają przeglądarce (nowa karta), zwykły klik przełącza
 * widok w miejscu, bez przeładowania strony.
 */
function ViewTab({ view, activeView, onViewChange, href, testId, children }: ViewTabProps) {
  const className = cn(
    "inline-flex h-7 items-center gap-1.5 rounded-md px-3 text-[13px] font-medium transition-colors pointer-coarse:h-9",
    activeView === view
      ? "bg-card text-primary shadow-sm"
      : "text-muted-foreground hover:text-foreground",
  );
  const ariaCurrent = activeView === view ? ("page" as const) : undefined;
  if (href == null) {
    return (
      <button
        type="button"
        onClick={() => onViewChange(view)}
        aria-current={ariaCurrent}
        data-testid={testId}
        className={className}
      >
        {children}
      </button>
    );
  }
  return (
    <a
      href={href}
      onClick={(event: MouseEvent<HTMLAnchorElement>) => {
        if (!isPlainLeftClick(event)) return;
        event.preventDefault();
        onViewChange(view);
      }}
      aria-current={ariaCurrent}
      data-testid={testId}
      className={className}
    >
      {children}
    </a>
  );
}

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
 *
 * 14.10.2026 (K-D1–K-D5, https://claude.ai/artifact/DZWUbWtiQLrnzm81RwLvDP):
 * jedna karta w trzech cienkich liniach, bo przy 1280×720 nagłówek z paskiem
 * kandydatów zabierał prawie pół ekranu — (1) priorytet, tytuł, status,
 * zakładki, ikona „Historia i czat”, „⋯”, „Zwiń”; (2) fakty z ikoną
 * i „Rekruter”; (3) na Tablicy źródła kandydatów i „Kto dodał”. Nazwa od
 * klienta i numery są w dymku tytułu. Zwinięty = sama linia 1.
 *
 * 15.10.2026 (D2): championów wskazuje się w okienku plakietki statusu.
 *
 * 25.10.2026: menu „⋯” z 17 pozycji na 9 — bez dubli nagłówka i okna
 * „Zlecenie”; przy 1280×720 dawne menu ucinało „Zamknij rekrutację…”.
 */
export function JobDetailCompactHeader({
  title,
  clientTitle,
  clientReference,
  onCopyClientReference,
  referenceNumber,
  badges,
  facts,
  priority,
  p0Strip,
  recruiter,
  recruiterCompact,
  sources,
  sourcesTrailing,
  collapsed = false,
  onToggleCollapsed,
  collapsedExtras,
  presence,
  activeView,
  onViewChange,
  viewHref,
  orderMissingCount,
  onOpenHistoryChat,
  chatUnreadCount = 0,
  onOpenFiles,
  filesCount,
  onOpenOrder,
  onEditFullChampion,
  onAddByName,
  onAddFromCv,
  onStartFullReview,
  onOpenMyPeople,
  onEdit,
  onWriteAnnouncement,
  adChannels = null,
  onGenerateInviteLink,
  onOpenAiTools,
  onCopyLink,
  onCloseJob,
  onReopenJob,
  onChangeCloseReason,
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
    <header
      className="space-y-1.5 rounded-lg border border-border bg-card px-3 py-2"
      data-testid="job-header"
      data-collapsed={collapsed ? "true" : undefined}
    >
      {p0Strip}
      {/* `flex-wrap`: w wąskim oknie zakładki i przyciski schodzą pod tytuł,
          zamiast go ucinać. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {/* Priorytet, tytuł w jednej linii i status obok (14.10.2026, K1):
            pełny tytuł i nazwa od klienta w dymku. Tytuł ma nie mniej niż 6rem. */}
        <div className="flex min-w-0 flex-[1_1_22rem] items-center gap-2">
          {priority}
          {/* Numer u klienta przed tytułem, także po „Zwiń” (prośba DL
              Nordei, 15.10.2026): tytuły dla rekrutera są uogólnione. */}
          <ClientReferenceChip
            reference={clientReference}
            clientTitle={clientTitle}
            size="header"
            onCopy={(reference) => onCopyClientReference?.(reference)}
            testId="header-client-reference"
          />
          <h1
            className="min-w-[6rem] flex-[0_100_auto] truncate text-lg font-semibold leading-tight text-foreground"
            title={[title, ...(clientLine.length > 0 ? [clientLine.join(" · ")] : [])].join("\n")}
            data-testid="job-header-title"
          >
            {title}
          </h1>
          {/* Najpierw ustępuje tytuł (do 6rem, `flex-shrink` 100), dopiero potem
              odznaki — zawijają się w swojej kolumnie, a nie wychodzą pod
              zakładki (zgłoszenie 28.10.2026: „Archiwum z Traffita” i
              „Prowadzona w NEXUSIE” przy 1280 px przykrywały „Tablicę”). */}
          {badges ? (
            <div className="flex min-w-0 flex-wrap items-center gap-1.5">{badges}</div>
          ) : null}
          {collapsed ? recruiterCompact : null}
          {collapsed ? collapsedExtras : null}
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {/* Dwa widoki rekrutacji jako zakładki. Pełna lista „Do przejrzenia”
              (`tab=people`) nie jest zakładką — z niej wraca „Tablica”. */}
          <nav
            className="flex shrink-0 items-center gap-0.5 rounded-lg bg-muted p-0.5"
            aria-label="Widok rekrutacji"
          >
            <ViewTab
              view="board"
              activeView={activeView}
              onViewChange={onViewChange}
              href={viewHref?.("board")}
              testId="view-board"
            >
              {activeView !== "board" && activeView !== "champion" ? (
                <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
              ) : null}
              Tablica
            </ViewTab>
            <ViewTab
              view="champion"
              activeView={activeView}
              onViewChange={onViewChange}
              href={viewHref?.("champion")}
              testId="open-champion-profile"
            >
              <FileText className="h-3.5 w-3.5" aria-hidden="true" />
              Profil Championa
              {missing != null ? (
                <Badge variant="warning" size="sm" className="tabular-nums">
                  brakuje {missing}
                </Badge>
              ) : null}
            </ViewTab>
          </nav>

          {presence}

          {/* Na laptopie 1280 px sama ikona z kropkami (napis zabierałby tytułowi
              ok. 80 px — jak „Historia i czat”, K-D4); napis od 1440 px, nazwa
              w dymku i dla czytnika ekranu, a pełna pozycja także w menu „⋯”. */}
          {onWriteAnnouncement ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-8 gap-1.5 px-2"
              onClick={onWriteAnnouncement}
              aria-label={adButtonLabel(adChannels)}
              title={adButtonLabel(adChannels)}
              data-testid="open-job-ad"
            >
              <Megaphone className="h-4 w-4" aria-hidden="true" />
              <span className="hidden min-[1440px]:inline">Ogłoszenie</span>
              {adChannels ? (
                <span className="flex items-center gap-0.5" aria-hidden="true">
                  {AD_CHANNEL_LABELS.map(({ key }) => (
                    <span
                      key={key}
                      className={cn(
                        "h-1.5 w-1.5 rounded-full",
                        adChannels[key] ? "bg-success" : "border border-muted-foreground",
                      )}
                    />
                  ))}
                </span>
              ) : null}
            </Button>
          ) : null}

          {/* Sama ikona z licznikiem (K-D4, 14.10.2026): napis zabierał tytułowi
              ok. 100 px przy 1280 px. Nazwa w dymku i dla czytnika ekranu. */}
          <Button
            type="button"
            size="icon-sm"
            variant="outline"
            className="relative"
            onClick={onOpenHistoryChat}
            aria-label={unreadLabel}
            title="Historia i czat"
            data-testid="open-history-chat"
          >
            <MessageCircle className="h-4 w-4" aria-hidden="true" />
            {chatUnreadCount > 0 ? (
              <Badge
                variant="danger"
                size="sm"
                className="absolute -right-2 -top-2 min-w-4 justify-center px-1 tabular-nums"
                aria-hidden="true"
              >
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
              >
                <Ellipsis className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-64">
              {onFinishJob || onReopenJob || onChangeCloseReason ? (
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
                  {onChangeCloseReason ? (
                    <DropdownMenuItem
                      onSelect={() => deferMenuAction(onChangeCloseReason)}
                      data-testid="change-close-reason"
                    >
                      <PencilLine className="h-4 w-4" />
                      Zmień powód zamknięcia…
                    </DropdownMenuItem>
                  ) : null}
                  <DropdownMenuSeparator />
                </>
              ) : null}

              {/* 9 pozycji (decyzja Artura 25.10.2026,
                  https://claude.ai/artifact/Vd1qKUVRy1yGTAgXb7ofz6): bez
                  tego, co stoi w nagłówku — „Championi…” (plakietka statusu),
                  „Zespół” (fakt „Rekruter”), „Ogłoszenie” (megafon) — bez
                  „Baza pytań” i „Karta klienta” (okno „Zlecenie”) i bez
                  przełącznika pustych kolumn (Tablica pokazuje wszystkie).
                  Cztery sposoby dodania kandydata w jednym podmenu. */}
              {hasAdding ? (
                <>
                  <DropdownMenuSub>
                    <DropdownMenuSubTrigger className="gap-2" data-testid="menu-add-candidates">
                      <UserPlus className="h-4 w-4" />
                      Dodaj kandydatów
                    </DropdownMenuSubTrigger>
                    <DropdownMenuSubContent className="w-60">
                      {onAddByName ? (
                        <DropdownMenuItem
                          onSelect={() => deferMenuAction(onAddByName)}
                          data-testid="menu-add-by-name"
                        >
                          <UserPlus className="h-4 w-4" />
                          Po nazwisku
                        </DropdownMenuItem>
                      ) : null}
                      {onAddFromCv ? (
                        <DropdownMenuItem
                          onSelect={() => deferMenuAction(onAddFromCv)}
                          data-testid="menu-add-from-cv"
                        >
                          <FileUp className="h-4 w-4" />
                          Z pliku CV
                        </DropdownMenuItem>
                      ) : null}
                      {onOpenMyPeople ? (
                        <DropdownMenuItem
                          onSelect={() => deferMenuAction(onOpenMyPeople)}
                          data-testid="menu-my-people"
                        >
                          <Users className="h-4 w-4" />
                          Z moich ludzi
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
                    </DropdownMenuSubContent>
                  </DropdownMenuSub>
                  <DropdownMenuSeparator />
                </>
              ) : null}

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
                  Edytuj Profil Championa
                </DropdownMenuItem>
              ) : null}
              {onEdit ? (
                <DropdownMenuItem onSelect={() => deferMenuAction(onEdit)}>
                  <PencilLine className="h-4 w-4" />
                  Edytuj dane rekrutacji
                </DropdownMenuItem>
              ) : null}
              {onOpenFiles ? (
                <DropdownMenuItem
                  onSelect={() => deferMenuAction(onOpenFiles)}
                  data-testid="menu-files"
                >
                  <Paperclip className="h-4 w-4" />
                  {filesCount != null && filesCount > 0 ? `Pliki (${filesCount})` : "Pliki"}
                </DropdownMenuItem>
              ) : null}

              {onCopyLink || onGenerateInviteLink ? (
                <>
                  <DropdownMenuSeparator />
                  {onCopyLink ? (
                    <DropdownMenuItem
                      onSelect={() => deferMenuAction(onCopyLink)}
                      data-testid="copy-job-link"
                    >
                      <Copy className="h-4 w-4" />
                      Kopiuj link do rekrutacji
                    </DropdownMenuItem>
                  ) : null}
                  {onGenerateInviteLink ? (
                    <DropdownMenuItem
                      onSelect={() => deferMenuAction(onGenerateInviteLink)}
                      title="Link, przez który kandydat sam zgłasza się do tej rekrutacji"
                    >
                      <Link2 className="h-4 w-4" />
                      Link do zgłoszeń kandydatów
                    </DropdownMenuItem>
                  ) : null}
                </>
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

          {onToggleCollapsed ? (
            <Button
              type="button"
              size="icon-sm"
              variant="outline"
              onClick={onToggleCollapsed}
              aria-expanded={!collapsed}
              aria-label={collapsed ? "Rozwiń nagłówek" : "Zwiń nagłówek do jednej linii"}
              title={collapsed ? "Rozwiń nagłówek" : "Zwiń nagłówek — więcej miejsca na Tablicę"}
              data-testid="job-header-collapse"
              className={cn(collapsed && "border-primary/40 bg-primary/10")}
            >
              {collapsed ? (
                <ChevronDown className="h-4 w-4" aria-hidden="true" />
              ) : (
                <ChevronUp className="h-4 w-4" aria-hidden="true" />
              )}
            </Button>
          ) : null}
        </div>
      </div>

      {/* Nazwa od klienta i nasz numer (0380) — w dymku tytułu (K-D3,
          14.10.2026); tu zostają dla czytników ekranu. Numer u klienta stoi
          od 15.10.2026 przed tytułem (`ClientReferenceChip`). */}
      {clientTitle || referenceNumber ? (
        <p className="sr-only" data-testid="header-client-line">
          {clientTitle ? (
            <span data-testid="header-client-title">U klienta: „{clientTitle}”</span>
          ) : null}
          {referenceNumber ? (
            <span>
              {clientTitle ? " · " : ""}nasz nr {referenceNumber}
            </span>
          ) : null}
        </p>
      ) : null}

      {collapsed ? null : (
        <>
          {/* Klient · Budżet · Tryb pracy · Rekruter — rzeczy, które rekruter
              sprawdza przed każdym telefonem. Ikona zamiast etykiety (K-D2):
              jedna linia przy 1280 px; etykieta w dymku i dla czytnika ekranu.
              Pierwsza kurczy się nazwa klienta, budżet nigdy. Brak wartości to
              „nie podano”, nie pustka. */}
          <div className="flex min-w-0 flex-wrap items-center gap-1.5 lg:flex-nowrap">
            <dl
              className="flex min-w-0 flex-wrap items-center gap-1.5 lg:flex-nowrap"
              data-testid="job-header-facts"
            >
              {facts.map((fact) => {
                const Icon = FACT_ICON[fact.key];
                return (
                  <div
                    key={fact.key}
                    className={cn(
                      "flex h-7 min-w-0 items-center gap-1.5 rounded-md border border-primary/20 bg-primary/5 px-2.5",
                      FACT_SHRINK[fact.key],
                    )}
                    data-testid={`job-header-fact-${fact.key}`}
                    title={`${fact.label}: ${fact.value ?? "nie podano"}`}
                  >
                    <dt className="flex shrink-0 items-center">
                      <Icon className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
                      <span className="sr-only">{fact.label}</span>
                    </dt>
                    <dd
                      className={cn(
                        "min-w-0 truncate text-[13px] font-semibold leading-tight",
                        fact.value ? "text-foreground" : "font-normal text-muted-foreground",
                      )}
                    >
                      {fact.value ?? "nie podano"}
                    </dd>
                  </div>
                );
              })}
            </dl>
            {recruiter}
          </div>

          {/* Kandydaci do dodania + filtr „Kto dodał” — tylko na Tablicy
              (K-D1, 14.10.2026; do tego dnia osobny pasek nad Tablicą). */}
          {sources || sourcesTrailing ? (
            <div
              className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-border pt-1.5"
              data-testid="job-header-sources-row"
            >
              {sources ? <div className="min-w-0">{sources}</div> : null}
              {sourcesTrailing ? <div className="ml-auto">{sourcesTrailing}</div> : null}
            </div>
          ) : null}
        </>
      )}
    </header>
  );
}
