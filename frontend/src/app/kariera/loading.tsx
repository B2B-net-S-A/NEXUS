import { TerminalChrome } from "@/components/career/TerminalChrome";

/**
 * Własna granica ładowania strony kariery. Bez niej zadziałałby szkielet
 * pulpitu z `app/loading.tsx` — kandydat widziałby na chwilę jasne karty
 * i tabelę przed czarną stroną.
 */
export default function CareerLoading() {
  return (
    <>
      <TerminalChrome path="~/dynaminds/kariera — zsh" />
      <main className="kr-log" role="status" aria-live="polite">
        <span>
          <span className="kr-r" aria-hidden="true">
            ${" "}
          </span>
          ładowanie…
        </span>
      </main>
    </>
  );
}
