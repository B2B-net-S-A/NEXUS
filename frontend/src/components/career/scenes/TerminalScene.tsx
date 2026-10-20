"use client";

import { useState, type KeyboardEvent } from "react";

import { useScene } from "./SceneContext";
import { ItemName, itemAria, SceneFrame, SceneList } from "./SceneParts";

/**
 * Terminal (programista): działający terminal. `cat wymagania` daje listę
 * do zaznaczenia [x], `./sprawdz --ja` kompiluje wynik, `git log --proces`
 * pokazuje kroki, `./aplikuj` podświetla przycisk. Polecenie można też wpisać.
 */
export type TerminalCommand = "help" | "wym" | "spr" | "log" | "apl" | "err";

const COMMANDS: Record<string, TerminalCommand> = {
  help: "help",
  ls: "help",
  "cat wymagania": "wym",
  "cat wymagania.md": "wym",
  "./sprawdz --ja": "spr",
  "./sprawdz": "spr",
  "git log --proces": "log",
  "git log": "log",
  "./aplikuj": "apl",
  "./aplikuj.sh": "apl",
};

/** Rozpoznanie wpisanego polecenia (wielkość liter i spacje bez znaczenia). */
export function parseTerminalCommand(raw: string): { kind: TerminalCommand; text: string } {
  const text = raw.trim().toLocaleLowerCase("pl-PL").replace(/\s+/g, " ");
  if (!text) return { kind: "help", text: "help" };
  return { kind: COMMANDS[text] ?? "err", text };
}

/** Pasek `[####------]` z wyniku. */
export function buildBar(count: number, total: number): string {
  const width = 10;
  const filled = total > 0 ? Math.round((count / total) * width) : 0;
  return `[${"#".repeat(filled)}${"-".repeat(width - filled)}]`;
}

const HASHES = ["a1f3c09", "7be20d4", "c44e1a8", "HEAD"];

const CHIPS: { label: string; cmd: string }[] = [
  { label: "cat wymagania", cmd: "cat wymagania" },
  { label: "./sprawdz --ja", cmd: "./sprawdz --ja" },
  { label: "git log --proces", cmd: "git log --proces" },
  { label: "./aplikuj", cmd: "./aplikuj" },
];

export function TerminalScene() {
  const { items, extraNice, steps, login, handle, recruiterFirstName, isOn, toggle, count, total, still, pingApply } =
    useScene();
  const [cmd, setCmd] = useState<{ kind: TerminalCommand; text: string; run: number }>({
    kind: "help",
    text: "help",
    run: 0,
  });
  const [input, setInput] = useState("");

  const exec = (raw: string) => {
    const parsed = parseTerminalCommand(raw);
    setCmd((prev) => ({ ...parsed, run: prev.run + 1 }));
    setInput("");
    if (parsed.kind === "apl") pingApply();
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      exec(input);
    }
  };

  const missing = items.filter((_, i) => !isOn(i)).map((i) => i.name.toLocaleLowerCase("pl-PL"));
  const typed = still ? "" : cmd.run % 2 ? " kr-ty-a" : " kr-ty-b";

  return (
    <>
      <SceneFrame label="Terminal: sprawdź, jak pasujesz" className="kr-sc-terminal">
        <div className="kr-term-head" aria-hidden="true">
          <span className="kr-term-dot" />
          <span className="kr-term-dot" />
          <span className="kr-term-dot kr-term-dot-on" />
          <span className="kr-term-path">
            {login}: ~/rekrutacje/{handle}
          </span>
        </div>
        <div className="kr-term-out" aria-live="polite">
          <p className="kr-term-line">
            <span className="kr-r" aria-hidden="true">
              ${" "}
            </span>
            <span className={`kr-w kr-term-cmd${typed}`} key={cmd.run}>
              {cmd.text}
            </span>
          </p>
          <div className={still ? "" : "kr-term-appear"} key={`o${cmd.run}`}>
            {cmd.kind === "help" ? (
              <>
                <p className="kr-dim"># dostępne polecenia</p>
                <p>
                  <span className="kr-w">cat wymagania</span> <span className="kr-dim">— lista wymagań, zaznacz swoje</span>
                </p>
                <p>
                  <span className="kr-w">./sprawdz --ja</span> <span className="kr-dim">— skompiluj dopasowanie</span>
                </p>
                <p>
                  <span className="kr-w">git log --proces</span> <span className="kr-dim">— jak wygląda rekrutacja</span>
                </p>
                <p>
                  <span className="kr-w">./aplikuj</span> <span className="kr-dim">— formularz, 2 minuty</span>
                </p>
              </>
            ) : null}
            {cmd.kind === "wym" ? (
              <>
                <p className="kr-dim"># kliknij linię, którą masz — [x]</p>
                {items.map((item, i) => {
                  const on = isOn(i);
                  return (
                    <button
                      type="button"
                      key={item.key}
                      className="kr-term-ln"
                      aria-pressed={on}
                      aria-label={itemAria(item)}
                      onClick={() => toggle(i)}
                    >
                      <span className={on ? "kr-r" : "kr-dim"}>{on ? "[x]" : "[ ]"}</span>{" "}
                      <span className="kr-w"><ItemName item={item} /></span>
                      {item.note ? <span className="kr-dim"> {"// "}{item.note}</span> : null}
                    </button>
                  );
                })}
                {extraNice.length > 0 ? (
                  <p className="kr-dim kr-term-gap">
                    [--] mile widziane: {extraNice.map((n) => n.toLocaleLowerCase("pl-PL")).join(" · ")}
                  </p>
                ) : null}
              </>
            ) : null}
            {cmd.kind === "spr" ? (
              <>
                <p className="kr-dim">kompiluję dopasowanie…</p>
                <p>
                  <span className="kr-w">{buildBar(count, total)}</span>{" "}
                  <span className="kr-r">
                    {count}/{total}
                  </span>
                </p>
                <p className={count * 2 >= total && count > 0 ? "kr-r" : "kr-w"}>
                  {count === 0
                    ? "BUILD PENDING — najpierw: cat wymagania"
                    : count * 2 >= total
                      ? "BUILD SUCCESS"
                      : "BUILD OK z ostrzeżeniami"}
                </p>
                {count === total ? (
                  <p className="kr-dim">{"// komplet. czekamy na Ciebie"}</p>
                ) : count > 0 ? (
                  <p className="kr-dim">
                    {"// brakuje: "}
                    {missing.join(", ")} — nie szkodzi, aplikuj
                  </p>
                ) : null}
              </>
            ) : null}
            {cmd.kind === "log" ? (
              steps.length > 0 ? (
                steps.map((step, i) => (
                  <p key={step.title}>
                    <span className="kr-r">{HASHES[i] ?? "HEAD"}</span> <span className="kr-w">{step.title}</span>{" "}
                    <span className="kr-dim">{"// "}{step.note}</span>
                  </p>
                ))
              ) : (
                <p className="kr-dim"># kroki opowie {recruiterFirstName} na pierwszej rozmowie</p>
              )
            ) : null}
            {cmd.kind === "apl" ? (
              <>
                <p className="kr-w">otwieram formularz zgłoszenia…</p>
                <p>
                  <a href="#aplikuj">→ przejdź do formularza</a>{" "}
                  <span className="kr-dim">albo przycisk „Aplikuj” obok</span>
                </p>
              </>
            ) : null}
            {cmd.kind === "err" ? (
              <>
                <p className="kr-r">zsh: nie znam „{cmd.text}”</p>
                <p className="kr-dim">wpisz help albo kliknij polecenie niżej</p>
              </>
            ) : null}
          </div>
        </div>
        <div className="kr-term-chips">
          {CHIPS.map((c) => (
            <button type="button" key={c.cmd} className="kr-term-chip" onClick={() => exec(c.cmd)}>
              {c.label}
            </button>
          ))}
        </div>
        <label className="kr-term-input">
          <span className="kr-r" aria-hidden="true">
            $
          </span>
          <input
            aria-label="Polecenie terminala"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKey}
            placeholder="wpisz polecenie i Enter"
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
          />
        </label>
      </SceneFrame>
      <SceneList
        head={
          <>
            <span className="kr-r" aria-hidden="true">
              ${" "}
            </span>
            cat wymagania
          </>
        }
        hint="dotknij linii, którą masz — [x]"
        mark={(on) => (on ? "[x]" : "[ ]")}
      />
    </>
  );
}
