"use client";

import { useState } from "react";

import { useScene } from "./SceneContext";
import { ItemName, itemAria, SceneFrame, SceneList } from "./SceneParts";

/**
 * Papier (tester manualny): ekran logowania z czterema błędami do zakreślenia
 * (nie liczą się do wyniku) i scenariusz TC-001 — kroki, które umiesz = PASS.
 * Błędy to przyciski z opisem w `aria-label`, nie literówki czytane na głos.
 */
export const PAPER_BUGS = [
  { wrong: "Hsało", right: "Hasło", what: "literówka w etykiecie hasła" },
  { wrong: "31.02.2026", right: "28.02.2026", what: "data, która nie istnieje" },
  { wrong: "Anuluj", right: "Anuluj", what: "przycisk przesunięty poza linię" },
  { wrong: "Error: null", right: "Nieprawidłowy login lub hasło", what: "niezrozumiały komunikat błędu" },
] as const;

export function paperReport(found: number): string {
  return found >= PAPER_BUGS.length ? "zgłoszenia: 4/4 — komplet" : `zgłoszenia: ${found}/4`;
}

function Bug({ index, found, onFind }: { index: number; found: boolean; onFind: (i: number) => void }) {
  const bug = PAPER_BUGS[index];
  // Zakreślony błąd zostaje tym samym przyciskiem (aria-pressed) — fokus nie ginie.
  return (
    <button
      type="button"
      className={found ? "kr-paper-bug kr-paper-ok" : "kr-paper-bug"}
      data-bug={index}
      aria-pressed={found}
      aria-label={
        found
          ? `Błąd ${index + 1} z 4 zakreślony: ${bug.what}.`
          : `Błąd ${index + 1} z 4: ${bug.what}. Kliknij, żeby zakreślić.`
      }
      onClick={() => onFind(index)}
    >
      <span aria-hidden="true">{found ? bug.right : bug.wrong}</span>
    </button>
  );
}

function LoginMock({ bugs, onFind }: { bugs: boolean[]; onFind: (i: number) => void }) {
  const found = bugs.filter(Boolean).length;
  return (
    <div className="kr-paper-app">
      <p className="kr-paper-app-head">
        <b>Bankowość · logowanie</b>
        <span>wersja 4.2.0</span>
      </p>
      <p className="kr-paper-lbl">Login</p>
      <p className="kr-paper-inp" aria-hidden="true">
        jan.kowalski
      </p>
      <p className="kr-paper-lbl">
        <Bug index={0} found={bugs[0]} onFind={onFind} />
      </p>
      <p className="kr-paper-inp" aria-hidden="true">
        ••••••••
      </p>
      <p className="kr-paper-lbl">
        Data ostatniego logowania: <Bug index={1} found={bugs[1]} onFind={onFind} />
      </p>
      <p className="kr-paper-btns">
        <span className="kr-paper-login">Zaloguj</span>
        <span className="kr-paper-cancel" data-shifted={bugs[2] ? undefined : ""}>
          <Bug index={2} found={bugs[2]} onFind={onFind} />
        </span>
      </p>
      <p className="kr-paper-msg">
        Komunikat: <Bug index={3} found={bugs[3]} onFind={onFind} />
      </p>
      <p className="kr-paper-count" aria-live="polite" data-done={found >= 4 ? "" : undefined}>
        {paperReport(found)}
      </p>
    </div>
  );
}

export function PaperScene() {
  const { items, isOn, toggle, count, total } = useScene();
  const [bugs, setBugs] = useState<boolean[]>(() => PAPER_BUGS.map(() => false));
  const onFind = (i: number) => setBugs((prev) => prev.map((b, k) => (k === i ? true : b)));
  return (
    <>
      <SceneFrame label="Papier: zakreśl błędy i odhacz kroki scenariusza, które umiesz" className="kr-sc-paper">
        <LoginMock bugs={bugs} onFind={onFind} />
        <div className="kr-paper-tc">
          <p className="kr-paper-tc-head">
            <span>SCENARIUSZ TC-001 · CO UMIESZ</span>
            <span>
              {count} PASS · {total - count} DO SPR.
            </span>
          </p>
          {items.map((item, i) => {
            const on = isOn(i);
            return (
              <button
                type="button"
                key={item.key}
                className="kr-paper-step"
                aria-pressed={on}
                aria-label={itemAria(item)}
                data-on={on ? "" : undefined}
                onClick={() => toggle(i)}
              >
                <span className="kr-paper-chk" aria-hidden="true">
                  {on ? "✓" : ""}
                </span>
                <span>
                  <ItemName item={item} />
                  {item.note ? <span className="kr-paper-note"> — {item.note}</span> : null}
                </span>
                <span className="kr-paper-res">{on ? "PASS" : "DO SPR."}</span>
              </button>
            );
          })}
        </div>
      </SceneFrame>
      <SceneList
        head="SCENARIUSZ TC-001 · CO UMIESZ"
        hint="dotknij kroku, który umiesz — PASS"
        mark={(on) => (on ? "☑ PASS" : "☐ DO SPR.")}
        footer={
          <div className="kr-paper-compact-app">
            <p className="kr-scene-cl-hint">na ekranie logowania są 4 błędy — zakreśl je</p>
            <LoginMock bugs={bugs} onFind={onFind} />
          </div>
        }
      />
    </>
  );
}
