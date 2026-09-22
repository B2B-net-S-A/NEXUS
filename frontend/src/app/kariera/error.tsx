"use client";

import { TerminalChrome } from "@/components/career/TerminalChrome";

/** Awaria odczytu (np. API niedostępne) — w motywie kariery, z ponowieniem. */
export default function CareerError({ reset }: { error: Error; reset: () => void }) {
  return (
    <>
      <TerminalChrome path="~/dynaminds/kariera — zsh" />
      <main className="kr-log" role="alert">
        <span>
          <span className="kr-r">[err]</span> <span className="kr-g">503</span>{" "}
          <span className="kr-c">{"// nie udało się wczytać strony"}</span>
        </span>
        <h1 className="kr-log-title">
          <span className="kr-title-a">Chwilowa</span>{" "}
          <span className="kr-title-b">przerwa.</span>
        </h1>
        <span className="kr-log-text">Spróbuj ponownie za chwilę.</span>
        <button type="button" className="kr-btn" onClick={reset} style={{ border: 0, font: "inherit" }}>
          $ ./ponow
        </button>
      </main>
    </>
  );
}
