import type { Metadata } from "next";

import { CareerFooter } from "@/components/career/CareerFooter";
import { TerminalChrome } from "@/components/career/TerminalChrome";
import { CONSENT_TEXT } from "@/lib/career/apply";
import { careerHref } from "@/lib/career/host";

import { careerRequestContext } from "../_context";

export const metadata: Metadata = {
  title: "Klauzula informacyjna",
  robots: { index: false, follow: false },
};

/**
 * Klauzula informacyjna (art. 13 RODO) dla kandydatów aplikujących przez
 * stronę kariery. WERSJA ROBOCZA — miejsca oznaczone [DO UZUPEŁNIENIA]
 * wymagają decyzji prawnika przed uruchomieniem domeny publicznej.
 */
export default async function CareerRodoPage() {
  const { base, host } = await careerRequestContext();
  return (
    <>
      <TerminalChrome path="~/dynaminds/kariera — zsh — klauzula_rodo" />
      <main className="kr-doc">
        <p className="kr-draft" role="note">
          <span className="kr-r">[!]</span> Wersja robocza — do akceptacji prawnej.
        </p>
        <span className="kr-c">{"// cat /etc/dynaminds/klauzula_rodo.md"}</span>
        <h1>Klauzula informacyjna dla kandydatów</h1>

        <h2>1. Administrator danych</h2>
        <p>
          Administratorem Twoich danych osobowych jest B2B.NET S.A. z siedzibą w Warszawie,
          Aleje Jerozolimskie 180, 02-486 Warszawa, wpisana do rejestru przedsiębiorców
          Krajowego Rejestru Sądowego prowadzonego przez Sąd Rejonowy dla m.st. Warszawy,
          XII Wydział Gospodarczy KRS, pod numerem KRS 0000387063, NIP 5711707392.
        </p>

        <h2>2. Kontakt w sprawie danych osobowych</h2>
        <p>
          W sprawach dotyczących przetwarzania danych możesz napisać na adres:{" "}
          <strong>[DO UZUPEŁNIENIA — adres e-mail do spraw ochrony danych]</strong> albo
          listownie na adres siedziby administratora.
        </p>

        <h2>3. Cel i podstawa przetwarzania</h2>
        <p>
          Przetwarzamy Twoje dane w celu prowadzenia obecnych i przyszłych procesów
          rekrutacyjnych, w tym przedstawiania Ci propozycji projektów IT, na podstawie
          Twojej zgody (art. 6 ust. 1 lit. a RODO). Treść zgody:
        </p>
        <p>
          <em>„{CONSENT_TEXT}”</em>
        </p>

        <h2>4. Zakres danych</h2>
        <p>
          Imię i nazwisko, adres e-mail, CV wraz z danymi, które w nim umieścisz, oraz
          informacje podane dobrowolnie w formularzu: oczekiwana stawka, termin dostępności,
          miasto i preferowany tryb pracy.
        </p>

        <h2>5. Okres przechowywania</h2>
        <p>
          Dane przechowujemy do czasu wycofania zgody, nie dłużej jednak niż{" "}
          <strong>[DO UZUPEŁNIENIA — okres do potwierdzenia przez prawnika]</strong>.
        </p>

        <h2>6. Odbiorcy danych</h2>
        <p>
          Dane mogą być przekazywane podmiotom przetwarzającym je na zlecenie administratora
          (np. dostawcom usług IT i hostingu), a — wyłącznie za Twoją wiedzą w ramach
          konkretnego procesu — klientom, u których prowadzona jest rekrutacja.
        </p>

        <h2>7. Twoje prawa</h2>
        <ul>
          <li>dostęp do danych i otrzymanie ich kopii,</li>
          <li>sprostowanie, usunięcie lub ograniczenie przetwarzania danych,</li>
          <li>przeniesienie danych,</li>
          <li>
            wycofanie zgody w dowolnym momencie — bez wpływu na zgodność z prawem
            przetwarzania dokonanego przed jej wycofaniem,
          </li>
          <li>wniesienie skargi do Prezesa Urzędu Ochrony Danych Osobowych.</li>
        </ul>

        <h2>8. Dobrowolność</h2>
        <p>
          Podanie danych jest dobrowolne, ale niezbędne do udziału w rekrutacji. Nie
          podejmujemy wobec Ciebie decyzji opartych wyłącznie na zautomatyzowanym
          przetwarzaniu, które wywoływałyby skutki prawne.
        </p>
      </main>
      <CareerFooter rodoHref={careerHref(base, { to: "rodo" })} hostLabel={host} />
    </>
  );
}
