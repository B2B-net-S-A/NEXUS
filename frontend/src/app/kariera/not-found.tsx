import { TerminalChrome } from "@/components/career/TerminalChrome";
import { TwoToneTitle } from "@/components/career/CareerHero";

/** 404 strony kariery — także każdy adres spoza listy na hoście kariery. */
export default function CareerNotFound() {
  return (
    <>
      <TerminalChrome path="~/dynaminds/kariera — zsh" />
      <main className="kr-log">
        <span>
          <span className="kr-r" aria-hidden="true">
            ${" "}
          </span>
          cd ~/dynaminds/kariera
        </span>
        <span>
          <span className="kr-r">[err]</span> <span className="kr-g">404</span>{" "}
          <span className="kr-c">{"// nie ma takiej strony albo link wygasł"}</span>
        </span>
        <TwoToneTitle className="kr-log-title" first="Nie znaleziono" second="strony." inline />
        <span className="kr-log-text">
          Sprawdź, czy link z ogłoszenia jest kompletny. Aktualne rekrutacje publikują nasi
          rekruterzy na LinkedInie.
        </span>
      </main>
    </>
  );
}
