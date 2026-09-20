/**
 * Widok tablicy pipeline'u: „Widok przeglądowy" (kafelki) ↔ „Kolumny".
 *
 * Wyniesione z `KanbanBoardV2` do osobnego modułu z tego samego powodu co
 * `job-header-preferences.ts`: test ma się wiązać z TĄ SAMĄ wartością i TĄ
 * SAMĄ funkcją, których używa komponent. Asercja na literał wpisany ponownie
 * w teście sprawdza własną kopię i przestaje chronić w dniu, w którym oryginał
 * się zmieni.
 *
 * ## Dlaczego preferencja jest TRÓJSTANOWA, a nie `useLocalStorageFlag`
 *
 * Reszta przełączników UI (`zwinięty nagłówek", „zwinięta szyna") to boolean
 * z ustaloną wartością domyślną. Tutaj wartością domyślną jest WYNIK REGUŁY
 * („szeroki szablon otwiera się kafelkowo"), a nie stała — a to daje dwa
 * problemy, których boolean nie umie wyrazić:
 *
 * 1. `useLocalStorageFlag` zapisuje `"1"`/`"0"`, więc „użytkownik nigdy nie
 *    wybrał" jest nie do odróżnienia od „użytkownik wybrał kolumny". Szablon,
 *    który urośnie ponad próg, MUSI otworzyć się kafelkowo komuś, kto nigdy nie
 *    tknął przełącznika — i jednocześnie NIE MOŻE nadpisać wyboru komuś, kto
 *    jawnie wybrał kolumny. To są dwa różne stany.
 * 2. `useState(defaultValue)` liczy się raz, przy montażu. Liczba
 *    RENDEROWANYCH kolumn zmienia się w trakcie życia komponentu (przełącznik
 *    „pokaż puste kolumny": 9 ↔ 16), więc boolean z ruchomą wartością domyślną
 *    po cichu zostałby przy pierwszej obliczonej wartości.
 *
 * Stąd `"auto" | "tiles" | "columns"`. Dyscyplina zapisu jest ta sama co
 * w `useLocalStorageFlag`: odczyt w `useEffect` (nie w inicjalizatorze — SSR
 * nie ma `localStorage`, więc pierwszy render klienta rozjechałby się z HTML-em
 * z serwera), zapis w setterze (efekt na `[value]` odpaliłby się też przy
 * montażu i nadpisał zapamiętaną preferencję), wszystko w `try/catch`
 * (`localStorage` rzuca `SecurityError`, gdy przeglądarka blokuje dane witryn).
 */

import { useCallback, useEffect, useState } from "react";

export const KANBAN_VIEW_MODE_STORAGE_KEY = "nexus:kanbanViewMode:v1";

/**
 * Powyżej tylu RENDEROWANYCH kolumn tablica domyślnie otwiera się kafelkowo.
 *
 * Próg liczy się z liczby kolumn NA EKRANIE, nie z liczby etapów szablonu: po
 * zwinięciu pustych grup „Default B2B" pokazuje dziesięć kolumn zamiast
 * szesnastu. Dziesięć, nie dziewięć — to jest DOKŁADNIE tyle, ile zostaje
 * z „Default B2B" po zwinięciu grup „U klienta" i „Umowa → zatrudnieni", więc
 * próg o jeden niżej zostawiałby najczęstszy szablon w produkcie po gorszej
 * stronie granicy.
 */
export const OVERVIEW_COLUMN_THRESHOLD = 10;

/** Co użytkownik widzi. `auto` = „jeszcze nie wybrał, rozstrzyga reguła". */
export type KanbanViewMode = "tiles" | "columns";
export type KanbanViewPreference = KanbanViewMode | "auto";

function isPreference(value: string | null): value is KanbanViewPreference {
  return value === "auto" || value === "tiles" || value === "columns";
}

/**
 * Czy przełącznik ma się w ogóle pokazać.
 *
 * Poniżej progu kolumny mieszczą się bez przewijania w poziomie, więc jedyne,
 * co dałby „widok przeglądowy", to mniejsze karty — kontrolka, której wyłącznym
 * efektem jest pogorszenie widoku, jest szumem. Pokazujemy ją dokładnie wtedy,
 * gdy reguła automatyczna miała co rozstrzygać.
 */
export function kanbanViewToggleVisible({
  renderedColumns,
  fullPipelineDesktop,
}: {
  renderedColumns: number;
  fullPipelineDesktop: boolean;
}): boolean {
  return fullPipelineDesktop && renderedColumns > OVERVIEW_COLUMN_THRESHOLD;
}

/**
 * Preferencja + liczba kolumn → tryb, który faktycznie ma się wyrenderować.
 *
 * Poniżej progu wynik jest ZAWSZE `columns`, nawet przy zapamiętanym `tiles`:
 * przełącznika tam nie ma, więc kafelki na wąskim szablonie byłyby stanem bez
 * wyjścia — użytkownik widziałby ściśnięte karty i nie miałby czym tego cofnąć.
 * Preferencja NIE jest przy tym kasowana: wraca na szerokim szablonie.
 */
export function resolveKanbanViewMode(
  preference: KanbanViewPreference,
  context: { renderedColumns: number; fullPipelineDesktop: boolean },
): KanbanViewMode {
  if (!kanbanViewToggleVisible(context)) return "columns";
  return preference === "auto" ? "tiles" : preference;
}

export function useKanbanViewPreference(): [
  KanbanViewPreference,
  (next: KanbanViewPreference) => void,
] {
  const [preference, setPreference] = useState<KanbanViewPreference>("auto");

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(KANBAN_VIEW_MODE_STORAGE_KEY);
      if (isPreference(raw)) setPreference(raw);
    } catch {
      /* storage wyłączony — zostaje reguła automatyczna */
    }
  }, []);

  const set = useCallback((next: KanbanViewPreference) => {
    setPreference(next);
    try {
      window.localStorage.setItem(KANBAN_VIEW_MODE_STORAGE_KEY, next);
    } catch {
      /* preferencja UI — nie przerywamy interakcji */
    }
  }, []);

  return [preference, set];
}
