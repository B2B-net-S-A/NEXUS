"use client";

/**
 * Panel „Plan zmian” (Edytor CV 2, PR 4): operacje, które asystent proponuje
 * dla całego CV i które przeszły kontrolę serwera. Rekruter odznacza te,
 * których nie chce; „Zastosuj zaznaczone” nakłada resztę jedną cofalną zmianą.
 *
 * Tytuł operacji i miejsce w CV składa kod z wierszy dokumentu; zdanie
 * asystenta („dlaczego”) jest tylko dopiskiem. Teksty pokazujemy jako tekst.
 */

import { useId } from "react";
import { AlertTriangle, Loader2, LocateFixed, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import type { CvPlanOperation } from "@/lib/api/cvEditorCommand";
import type { CvLine } from "@/lib/cv-editor-command";

import { Marked } from "./CvAiProposalCard";
import { CV_COMMAND_ATTR } from "./CvEditorCommandBar";
import type { CvCommandController } from "./useCvCommandPlan";

function plural(count: number, one: string, few: string, many: string): string {
  const last = count % 10;
  const teen = count % 100 >= 12 && count % 100 <= 14;
  return count === 1 ? one : last >= 2 && last <= 4 && !teen ? few : many;
}

function plainText(text: string): string {
  return text.replace(/\*\*/g, "");
}

/** Gdzie w CV stoi wiersz: stanowisko albo sekcja, pod którą leży. */
function placeOf(line: CvLine, lines: readonly CvLine[]): string | null {
  if (line.role != null) {
    const role = lines.find((item) => item.kind === "role" && item.role === line.role);
    if (role) return plainText(role.text);
  }
  for (let index = line.id; index >= 0; index -= 1) {
    const item = lines[index];
    if (item?.kind === "heading") return plainText(item.text);
    if (item?.kind === "title") break;
  }
  return null;
}

export function operationTitle(operation: CvPlanOperation, lines: readonly CvLine[]): string {
  const rows = operation.lines.map((id) => lines[id]).filter((line): line is CvLine => line != null);
  const count = rows.length;
  const bullets = rows.every((line) => line.kind === "bullet");
  const item = (n: number) => (bullets ? plural(n, "punkt", "punkty", "punktów") : plural(n, "akapit", "akapity", "akapitów"));
  switch (operation.type) {
    case "remove":
      return count === 1 ? `Usuń ${item(1)}` : `Usuń ${count} ${item(count)}`;
    case "replace":
      return `Przeredaguj ${item(1)}`;
    case "merge":
      return `Połącz ${count} ${item(count)} w jeden`;
    case "reorder":
      return "Zmień kolejność punktów";
    case "remove_role":
      return "Usuń stanowisko";
    case "remove_section":
      return "Usuń sekcję";
  }
}

function Operation({ operation, controller }: { operation: CvPlanOperation; controller: CvCommandController }) {
  const id = useId();
  const { lines } = controller;
  const rows = operation.lines.map((line) => lines[line]).filter((line): line is CvLine => line != null);
  const first = rows[0];
  const place = first ? placeOf(first, lines) : null;
  const whole = operation.type === "remove_role" || operation.type === "remove_section";
  const changed = operation.type === "replace" || operation.type === "merge";
  const listed = whole ? [] : rows.slice(0, 3);
  const checked = controller.selected.has(operation.id);

  return (
    <li className="rounded-lg border border-border bg-background p-3" data-testid={`plan-operation-${operation.id}`}>
      <div className="flex items-start gap-2.5">
        <Checkbox
          id={id}
          checked={checked}
          disabled={controller.busy}
          onCheckedChange={() => controller.toggle(operation.id)}
          className="mt-0.5"
        />
        <div className="min-w-0 flex-1 space-y-1.5">
          <label htmlFor={id} className="block cursor-pointer text-sm font-semibold text-foreground">
            {operationTitle(operation, lines)}
            {place ? <span className="block text-xs font-normal text-muted-foreground [overflow-wrap:anywhere]">{place}</span> : null}
          </label>
          {operation.type === "reorder" ? (
            <ol className="list-decimal space-y-0.5 pl-4 text-xs text-muted-foreground">
              {rows.map((line) => (
                <li key={line.id} className="[overflow-wrap:anywhere]">
                  <Marked text={line.text} />
                </li>
              ))}
            </ol>
          ) : null}
          {operation.type !== "reorder" && listed.length > 0 ? (
            <ul className="space-y-0.5 text-xs text-muted-foreground">
              {listed.map((line) => (
                <li key={line.id} className="line-through decoration-destructive/60 [overflow-wrap:anywhere]">
                  <Marked text={line.text} />
                </li>
              ))}
              {rows.length > listed.length ? <li>i jeszcze {rows.length - listed.length}</li> : null}
            </ul>
          ) : null}
          {changed && operation.text ? (
            <p className="rounded-md bg-success-muted px-2 py-1.5 text-xs text-foreground [overflow-wrap:anywhere]">
              <Marked text={operation.text} />
            </p>
          ) : null}
          {operation.why ? <p className="text-xs text-muted-foreground [overflow-wrap:anywhere]">Asystent: {operation.why}</p> : null}
          {operation.new_words.length > 0 ? (
            <p className="flex items-start gap-1.5 text-xs text-warning-muted-foreground">
              <AlertTriangle className="mt-0.5 size-3.5 flex-none" aria-hidden />
              <span>
                Nowe słowa, których nie było w tym miejscu: {operation.new_words.join(", ")}. Przeczytaj nową treść, zanim
                zaznaczysz.
              </span>
            </p>
          ) : null}
          {operation.loses.length > 0 ? (
            <p className="flex items-start gap-1.5 text-xs text-destructive">
              <AlertTriangle className="mt-0.5 size-3.5 flex-none" aria-hidden />
              <span>
                Po tej zmianie z CV {plural(operation.loses.length, "znika wymaganie", "znikają wymagania", "znikają wymagania")} klienta:{" "}
                {operation.loses.join(", ")}.
              </span>
            </p>
          ) : null}
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-6 px-1.5 text-xs text-primary"
            onClick={() => controller.show(operation.id)}
          >
            <LocateFixed className="mr-1 size-3" aria-hidden />
            Pokaż w CV
          </Button>
        </div>
      </div>
    </li>
  );
}

export interface CvEditorPlanProps {
  controller: CvCommandController;
  /** Wąski ekran: przejście na kartkę po „Pokaż w CV”. */
  onShowCv?: () => void;
}

export function CvEditorPlan({ controller, onShowCv }: CvEditorPlanProps) {
  const { phase, operations, selected, dropped, effect } = controller;
  const chosen = operations.filter((operation) => selected.has(operation.id)).length;
  const shorter = effect.before > 0 ? Math.round(((effect.before - effect.after) / effect.before) * 100) : 0;
  const shown: CvCommandController = onShowCv
    ? {
        ...controller,
        show: (id) => {
          onShowCv();
          // Kartka jest jeszcze ukryta — przewijamy po jej pokazaniu.
          setTimeout(() => controller.show(id), 50);
        },
      }
    : controller;

  return (
    <section
      {...{ [CV_COMMAND_ATTR]: "" }}
      aria-label="Plan zmian"
      className="flex h-full min-h-0 flex-col"
      onKeyDown={(event) => {
        if (event.key !== "Escape") return;
        event.stopPropagation();
        event.preventDefault();
      }}
    >
      <header className="flex-none space-y-1 border-b border-border px-4 py-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <Sparkles className="size-4 text-primary" aria-hidden />
          Plan zmian
        </h2>
        {phase === "plan" ? (
          <p className="text-xs text-muted-foreground">
            {operations.length} {plural(operations.length, "zmiana", "zmiany", "zmian")} · odznacz te, których nie chcesz. Na kartce
            widać podgląd — nic nie jest jeszcze zapisane.
          </p>
        ) : null}
      </header>

      <div className="min-h-0 flex-1 space-y-3 overflow-auto px-4 py-3">
        {phase === "loading" ? (
          <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden />
            Asystent przygotowuje plan zmian…
          </p>
        ) : null}
        {phase === "message" ? (
          <p role="status" className="text-sm text-muted-foreground">
            {controller.message}
          </p>
        ) : null}
        {phase === "plan" ? (
          <>
            <ul className="space-y-2">
              {operations.map((operation) => (
                <Operation key={operation.id} operation={operation} controller={shown} />
              ))}
            </ul>
            {shorter > 0 ? (
              <p className="text-xs text-muted-foreground">
                Po zaznaczonych zmianach treść CV będzie krótsza o około {shorter}% (z {effect.before} do {effect.after} znaków).
              </p>
            ) : null}
            <p className="text-xs text-muted-foreground">
              Kontrola sprawdziła liczby, daty, nazwy i wymagania klienta. Przeredagowania z nowymi słowami nie są zaznaczone
              — przeczytaj je przed zastosowaniem.
              {dropped > 0
                ? ` Odrzuciła ${dropped} ${plural(dropped, "propozycję", "propozycje", "propozycji")} asystenta (dopisywały fakty albo ruszały układ szablonu).`
                : ""}
            </p>
          </>
        ) : null}
      </div>

      <footer className="flex-none space-y-2 border-t border-border px-4 py-3">
        {phase === "plan" ? (
          <p className="text-xs text-muted-foreground">Po zastosowaniu wszystko cofniesz jednym „Cofnij”.</p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          {phase === "plan" ? (
            <Button size="sm" disabled={chosen === 0 || controller.busy} onClick={() => void controller.apply()}>
              {controller.busy ? <Loader2 className="mr-1.5 size-3.5 animate-spin" aria-hidden /> : null}
              Zastosuj zaznaczone ({chosen})
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" disabled={controller.busy} onClick={controller.discard}>
            {phase === "plan" ? "Odrzuć plan" : phase === "loading" ? "Anuluj" : "Zamknij"}
          </Button>
        </div>
      </footer>
    </section>
  );
}
