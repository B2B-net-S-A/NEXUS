import type { Metadata } from "next";

import { BrandPage, brandStyles as s } from "@/components/career/brand/BrandShell";
import { CareerThemeScope } from "@/components/career/CareerThemeScope";
import { CONSENT_CURRENT_TEXT, CONSENT_FUTURE_TEXT } from "@/lib/career/apply";
import { careerHref } from "@/lib/career/host";

import { careerRequestContext } from "../_context";

export const metadata: Metadata = {
  title: "Klauzula informacyjna",
  robots: { index: false, follow: false },
};

/**
 * Klauzula informacyjna (art. 13 RODO) dla kandydatów aplikujących przez
 * stronę kariery. Kontakt i okres przechowywania — decyzja właściciela
 * 27.09.2026 (runda 10 audytu, F16 z testów manualnych).
 */
export default async function CareerRodoPage() {
  const { base, host } = await careerRequestContext();
  return (
    <CareerThemeScope theme="grafit">
      <BrandPage
        homeHref={careerHref(base, { to: "home" })}
        rodoHref={careerHref(base, { to: "rodo" })}
        hostLabel={host}
      >
        <main className={`${s.wrap} ${s.doc}`}>
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
            <a href="mailto:rodo@b2bnetwork.pl">rodo@b2bnetwork.pl</a> albo
            listownie na adres siedziby administratora.
          </p>

          <h2>3. Cel i podstawa przetwarzania</h2>
          <p>
            Dane z formularza przetwarzamy w celu przeprowadzenia rekrutacji, na którą
            przesyłasz zgłoszenie, na podstawie Twojej zgody (art. 6 ust. 1 lit. a RODO):
          </p>
          <p>
            <em>„{CONSENT_CURRENT_TEXT}”</em>
          </p>
          <p>
            Jeśli zaznaczysz drugą, dobrowolną zgodę, przetwarzamy je także w celu
            prowadzenia przyszłych procesów rekrutacyjnych, w tym przedstawiania Ci
            propozycji innych projektów IT:
          </p>
          <p>
            <em>„{CONSENT_FUTURE_TEXT}”</em>
          </p>
          <p>Brak drugiej zgody nie wpływa na udział w tej rekrutacji.</p>
          <p>
            Jeśli zostawiasz CV na stałej stronie rekrutera („Dołącz do bazy”), zgłoszenie
            nie dotyczy konkretnej rekrutacji — prosimy wtedy tylko o zgodę na przyszłe procesy
            rekrutacyjne i jest ona obowiązkowa.
          </p>

          <h2>4. Zakres danych</h2>
          <p>
            Imię i nazwisko, adres e-mail, CV wraz z danymi, które w nim umieścisz, oraz
            informacje podane dobrowolnie w formularzu: oczekiwana stawka, termin dostępności,
            miasto i preferowany tryb pracy.
          </p>

          <h2>5. Okres przechowywania</h2>
          <p>
            Dane przechowujemy do czasu wycofania zgody, nie dłużej jednak niż 3 lata od
            przesłania zgłoszenia.
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
      </BrandPage>
    </CareerThemeScope>
  );
}
