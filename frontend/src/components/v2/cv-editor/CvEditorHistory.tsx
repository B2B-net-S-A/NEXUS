"use client";

/**
 * Panel „Historia wersji” w edytorze CV (Edytor CV 2, PR 5, decyzja D4).
 *
 * Lista zatwierdzonych wersji i „Wgraj poprawiony plik Word”. Obie drogi
 * prowadzą przez ten sam widok: lista RÓŻNIC z bieżącą treścią edytora,
 * a dopiero potem „Przywróć treść wersji N” / „Wstaw treść z pliku Word” —
 * jedna cofalna zmiana, którą utrwala zwykły autozapis.
 *
 * Teksty wersji i pliku pokazujemy jako tekst (`**x**` → pogrubienie w React),
 * nigdy jako HTML.
 */

import { useEffect, useRef } from "react";
import { Download, FileUp, History, Loader2, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { CvVersionSummary } from "@/lib/api/cvEditorHistory";
import { CV_DIFF_LINES_MAX, type CvDiffItem } from "@/lib/cv-editor-diff";
import { countForm } from "@/lib/cv-qc";

import { CV_PANEL_ATTR, Marked } from "./Marked";
import type { CvHistoryComparison, CvHistoryController, CvHistorySource } from "./useCvHistory";

/** Tyle różnic pokazuje lista; reszta to „i jeszcze N”. */
const DIFF_ITEMS_SHOWN = 60;

// Data zatwierdzenia w kalendarzu firmy, nie w strefie przeglądarki.
const APPROVED_AT = new Intl.DateTimeFormat("pl-PL", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Warsaw",
});

function approvedLabel(version: CvVersionSummary): string {
  const time = version.approved_at ? Date.parse(version.approved_at) : NaN;
  const when = Number.isFinite(time) ? `zatwierdzona ${APPROVED_AT.format(new Date(time))}` : "zatwierdzona";
  return version.approved_by_name ? `${when} · ${version.approved_by_name}` : when;
}

/** „wersji 2” / „pliku Word” — do zdań „w …”, „tylko w …”. */
function sourceName(source: CvHistorySource): string {
  return source.kind === "version" ? `wersji ${source.version}` : "pliku Word";
}

function VersionRow({ version, controller }: { version: CvVersionSummary; controller: CvHistoryController }) {
  const waiting = controller.loading != null || controller.busy;
  return (
    <li className="space-y-1.5 rounded-lg border border-border bg-background p-3" data-testid={`history-version-${version.version}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-foreground">Wersja {version.version}</span>
        {version.is_current ? (
          <Badge variant="info" size="sm">
            bieżąca
          </Badge>
        ) : null}
      </div>
      <p className="text-xs text-muted-foreground [overflow-wrap:anywhere]">{approvedLabel(version)}</p>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" disabled={waiting} onClick={() => controller.compare(version.version)}>
          {controller.loading === version.version ? <Loader2 className="mr-1.5 size-3.5 animate-spin" aria-hidden /> : null}
          Porównaj
        </Button>
        {version.docx_available ? (
          <Button
            size="sm"
            variant="ghost"
            disabled={controller.downloading != null}
            onClick={() => controller.download(version.version)}
          >
            {controller.downloading === version.version ? (
              <Loader2 className="mr-1.5 size-3.5 animate-spin" aria-hidden />
            ) : (
              <Download className="mr-1.5 size-3.5" aria-hidden />
            )}
            Pobierz DOCX
          </Button>
        ) : null}
      </div>
    </li>
  );
}

function VersionList({ controller }: { controller: CvHistoryController }) {
  const fileInput = useRef<HTMLInputElement>(null);
  const waiting = controller.loading != null || controller.busy;
  return (
    <>
      <header className="flex flex-none items-center gap-2 border-b border-border px-4 py-3">
        <History className="size-4 flex-none text-primary" aria-hidden />
        <h2 className="min-w-0 flex-1 text-sm font-semibold">Historia wersji</h2>
        <Button size="icon-sm" variant="ghost" aria-label="Zamknij historię" onClick={controller.close}>
          <X className="size-4" aria-hidden />
        </Button>
      </header>

      {controller.message ? (
        // Poza przewijaną listą: komunikat widać także wtedy, gdy wersji jest dużo.
        <p
          role="alert"
          className="flex-none border-b border-border bg-destructive-muted px-4 py-2 text-xs text-destructive-muted-foreground [overflow-wrap:anywhere]"
        >
          {controller.message}
        </p>
      ) : null}

      <section aria-label="Zatwierdzone wersje" className="min-h-0 flex-1 space-y-2 overflow-auto px-4 py-3">
        {controller.listState === "loading" ? (
          <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden />
            Wczytuję historię wersji…
          </p>
        ) : null}
        {controller.listState === "error" ? (
          <div role="alert" className="space-y-2 rounded-lg border border-border px-3 py-2 text-sm text-muted-foreground">
            <p className="[overflow-wrap:anywhere]">{controller.listError}</p>
            <Button size="sm" variant="outline" onClick={controller.reload}>
              Ponów
            </Button>
          </div>
        ) : null}
        {controller.listState === "ready" && controller.versions.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            To CV nie było jeszcze zatwierdzone — historia pojawi się po pierwszym „Zapisz”.
          </p>
        ) : null}
        {controller.listState === "ready" && controller.versions.length > 0 ? (
          <ul className="space-y-2">
            {controller.versions.map((version) => (
              <VersionRow key={version.version} version={version} controller={controller} />
            ))}
          </ul>
        ) : null}
      </section>

      <footer className="flex-none space-y-2 border-t border-border px-4 py-3">
        <p className="text-xs text-muted-foreground">
          Jeśli ktoś poprawił CV w Wordzie, wgraj plik — zobaczysz różnice, zanim cokolwiek się zmieni.
        </p>
        <input
          ref={fileInput}
          type="file"
          hidden
          accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          aria-label="Plik Word z poprawionym CV"
          data-testid="history-word-file"
          onChange={(event) => {
            const file = event.target.files?.[0];
            // Ten sam plik wybrany drugi raz też ma zgłosić zmianę.
            event.target.value = "";
            if (file) controller.importWord(file);
          }}
        />
        <Button size="sm" variant="outline" disabled={waiting} onClick={() => fileInput.current?.click()}>
          {controller.loading === "word" ? (
            <Loader2 className="mr-1.5 size-3.5 animate-spin" aria-hidden />
          ) : (
            <FileUp className="mr-1.5 size-3.5" aria-hidden />
          )}
          Wgraj poprawiony plik Word
        </Button>
      </footer>
    </>
  );
}

function DiffItem({ item, source }: { item: CvDiffItem; source: CvHistorySource }) {
  const from = sourceName(source);
  const title =
    item.kind === "changed"
      ? "Zmienione"
      : item.kind === "added"
        ? `Tylko w ${from} — dojdzie do CV`
        : "Tylko w bieżącej treści — zniknie z CV";
  return (
    <li className="space-y-1 rounded-lg border border-border bg-background p-2.5 text-xs" data-diff-kind={item.kind}>
      <p className="font-semibold text-foreground">{title}</p>
      {item.place ? <p className="text-muted-foreground [overflow-wrap:anywhere]">{item.place}</p> : null}
      {item.before != null ? (
        <p className="text-muted-foreground [overflow-wrap:anywhere]">
          {item.kind === "changed" ? <span className="font-medium">Teraz: </span> : null}
          <del className="decoration-destructive/60">
            <Marked text={item.before} />
          </del>
        </p>
      ) : null}
      {item.after != null ? (
        <p className="rounded-md bg-success-muted px-2 py-1.5 text-foreground [overflow-wrap:anywhere]">
          {item.kind === "changed" ? <span className="font-medium">W {from}: </span> : null}
          <ins className="no-underline">
            <Marked text={item.after} />
          </ins>
        </p>
      ) : null}
    </li>
  );
}

function Comparison({ comparison, controller }: { comparison: CvHistoryComparison; controller: CvHistoryController }) {
  const { source, diff } = comparison;
  const shown = diff?.slice(0, DIFF_ITEMS_SHOWN) ?? [];
  const more = (diff?.length ?? 0) - shown.length;
  return (
    <>
      <header className="flex-none space-y-1 border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold [overflow-wrap:anywhere]">
          {source.kind === "version" ? `Wersja ${source.version}` : `Plik Word: ${source.filename}`} a bieżąca treść
        </h2>
        <p role="status" className="text-xs text-muted-foreground">
          {diff == null
            ? `Za dużo wierszy, żeby pokazać różnice (ponad ${CV_DIFF_LINES_MAX}) — bez listy różnic tej treści nie wstawiamy.`
            : diff.length === 0
              ? "Treść jest taka sama."
              : countForm(diff.length, ["różnica", "różnice", "różnic"])}
        </p>
      </header>

      <div className="min-h-0 flex-1 space-y-2 overflow-auto px-4 py-3">
        {shown.length > 0 ? (
          <ul className="space-y-2">
            {shown.map((item, index) => (
              <DiffItem key={index} item={item} source={source} />
            ))}
          </ul>
        ) : null}
        {more > 0 ? <p className="text-xs text-muted-foreground">i jeszcze {more}</p> : null}
      </div>

      <footer className="flex-none space-y-2 border-t border-border px-4 py-3">
        {diff != null && diff.length > 0 ? (
          <p className="text-xs text-muted-foreground">Klauzula zgody i układ szablonu zostają z bieżącej wersji.</p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          {diff != null && diff.length > 0 ? (
            <Button size="sm" disabled={controller.busy} onClick={() => void controller.apply()}>
              {controller.busy ? <Loader2 className="mr-1.5 size-3.5 animate-spin" aria-hidden /> : null}
              {source.kind === "version" ? `Przywróć treść wersji ${source.version}` : "Wstaw treść z pliku Word"}
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" disabled={controller.busy} onClick={controller.back}>
            Wróć do listy
          </Button>
        </div>
      </footer>
    </>
  );
}

export interface CvEditorHistoryProps {
  controller: CvHistoryController;
}

export function CvEditorHistory({ controller }: CvEditorHistoryProps) {
  const root = useRef<HTMLElement>(null);
  const comparing = controller.comparison != null;
  // Przycisk, który przełączył widok, znika razem z nim — fokus zostaje w panelu,
  // żeby Escape nie trafił w `body` i nie zamknął całego edytora. Fokusu, który
  // jest już gdzie indziej (kartka po nałożeniu treści), nie zabieramy.
  useEffect(() => {
    const active = document.activeElement;
    if (!active || active === document.body) root.current?.focus({ preventScroll: true });
  }, [comparing]);

  return (
    <section
      ref={root}
      tabIndex={-1}
      // Ten sam znacznik co pasek polecenia i plan zmian: Escape w panelu nie zamyka edytora.
      {...{ [CV_PANEL_ATTR]: "" }}
      aria-label="Historia wersji"
      className="flex h-full min-h-0 flex-col outline-none"
      onKeyDown={(event) => {
        if (event.key !== "Escape") return;
        event.stopPropagation();
        event.preventDefault();
      }}
    >
      {controller.comparison ? (
        <Comparison comparison={controller.comparison} controller={controller} />
      ) : (
        <VersionList controller={controller} />
      )}
    </section>
  );
}
