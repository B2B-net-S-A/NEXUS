import type { Metadata } from "next";

import { TerminalChrome } from "@/components/career/TerminalChrome";
import { TwoToneTitle } from "@/components/career/CareerHero";
import { CareerFooter } from "@/components/career/CareerFooter";
import { careerHref } from "@/lib/career/host";

import { careerRequestContext } from "./_context";

export const metadata: Metadata = { title: "Kariera" };

/**
 * Strona startowa hosta kariery. Nie ma tu listy rekrutacji (każdy rekruter ma
 * własny link) — tylko kierunek, gdzie ich szukać.
 */
export default async function CareerHome() {
  const { base, host } = await careerRequestContext();
  return (
    <>
      <TerminalChrome path="~/b2bnetwork/kariera — zsh" />
      <main className="kr-log">
        <span>
          <span className="kr-r" aria-hidden="true">
            ${" "}
          </span>
          cat ~/b2bnetwork/kariera/README
        </span>
        <TwoToneTitle className="kr-log-title" first="Rekrutacje IT" second="B2B Network." />
        <span className="kr-log-text">
          Tu trafiają kandydaci z linków naszych rekruterów. Otwarte rekrutacje znajdziesz
          w postach zespołu B2B Network na LinkedInie.
        </span>
        <span className="kr-c">{"// zajrzyj na LinkedIn rekruterów B2B Network"}</span>
      </main>
      <CareerFooter rodoHref={careerHref(base, { to: "rodo" })} hostLabel={host} />
    </>
  );
}
