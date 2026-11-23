import type { Metadata } from "next";

import { SiteFrame, siteStyles as s } from "@/components/career/site/SiteFrame";
import { COMPANY_LEGAL_LINE } from "@/components/career/CareerFooter";
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
 * 27.09.2026 (runda 10 audytu, F16 z testów manualnych). Od 23.11.2026
 * w układzie nowej strony (plansza KlauzulaRodo); treść bez zmian.
 */
export default async function CareerRodoPage() {
  const { base } = await careerRequestContext();
  const homeHref = careerHref(base, { to: "home" });
  return (
    <SiteFrame homeHref={homeHref} rodoHref={careerHref(base, { to: "rodo" })}>
      <main>
        <section className={`${s.ch} ${s.chRed} ${s.rodo1}`}>
          <div className={`${s.wrap} ${s.rodo1Inner}`}>
            <span aria-hidden="true" className={`${s.display} ${s.rodoWord}`}>
              RODO
            </span>
            <div>
              <h1 className={s.lead}>Klauzula informacyjna dla kandydatów</h1>
              <a className={s.ulink} href={homeHref}>
                Wszystkie rekrutacje →
              </a>
            </div>
          </div>
        </section>
        <section className={`${s.ch} ${s.chSnow} ${s.rodo2}`} aria-label="Klauzula">
          <div className={s.wrap}>
            <article className={s.it}>
              <span aria-hidden="true" className={s.itNo}>
                1
              </span>
              <h2>
                <span className={s.srOnly}>1.</span>{" "}
                Administrator danych
              </h2>
              <div className={s.tx}>
                <p>
                  Administratorem Twoich danych osobowych jest B2B.NET S.A. z siedzibą w Warszawie, Aleje
                  Jerozolimskie 180, 02-486 Warszawa, wpisana do rejestru przedsiębiorców Krajowego Rejestru
                  Sądowego prowadzonego przez Sąd Rejonowy dla m.st. Warszawy, XII Wydział Gospodarczy KRS,
                  pod numerem KRS 0000387063, NIP 5711707392.
                </p>
              </div>
            </article>
            <article className={s.it}>
              <span aria-hidden="true" className={s.itNo}>
                2
              </span>
              <h2>
                <span className={s.srOnly}>2.</span>{" "}
                Kontakt w sprawie danych osobowych
              </h2>
              <div className={s.tx}>
                <p>
                  W sprawach dotyczących przetwarzania danych możesz napisać na adres:{" "}
                  <a href="mailto:rodo@b2bnetwork.pl">rodo@b2bnetwork.pl</a> albo listownie na adres siedziby
                  administratora.
                </p>
              </div>
            </article>
            <article className={s.it}>
              <span aria-hidden="true" className={s.itNo}>
                3
              </span>
              <h2>
                <span className={s.srOnly}>3.</span>{" "}
                Cel i podstawa przetwarzania
              </h2>
              <div className={s.tx}>
                <p>
                  Dane z formularza przetwarzamy w celu przeprowadzenia rekrutacji, na którą przesyłasz
                  zgłoszenie, na podstawie Twojej zgody (art. 6 ust. 1 lit. a RODO):
                </p>
                <blockquote>„{CONSENT_CURRENT_TEXT}”</blockquote>
                <p>
                  Jeśli zaznaczysz drugą, dobrowolną zgodę, przetwarzamy je także w celu prowadzenia
                  przyszłych procesów rekrutacyjnych, w tym przedstawiania Ci propozycji innych projektów IT:
                </p>
                <blockquote>„{CONSENT_FUTURE_TEXT}”</blockquote>
                <p>Brak drugiej zgody nie wpływa na udział w tej rekrutacji.</p>
                <p>
                  Jeśli zostawiasz CV na stałej stronie rekrutera („Dołącz do bazy”), zgłoszenie nie dotyczy
                  konkretnej rekrutacji — prosimy wtedy tylko o zgodę na przyszłe procesy rekrutacyjne i jest
                  ona obowiązkowa.
                </p>
              </div>
            </article>
            <article className={s.it}>
              <span aria-hidden="true" className={s.itNo}>
                4
              </span>
              <h2>
                <span className={s.srOnly}>4.</span>{" "}
                Zakres danych
              </h2>
              <div className={s.tx}>
                <p>
                  Imię i nazwisko, adres e-mail, CV wraz z danymi, które w nim umieścisz, oraz informacje
                  podane dobrowolnie w formularzu: oczekiwana stawka, termin dostępności, miasto i preferowany
                  tryb pracy.
                </p>
              </div>
            </article>
            <article className={s.it}>
              <span aria-hidden="true" className={s.itNo}>
                5
              </span>
              <h2>
                <span className={s.srOnly}>5.</span>{" "}
                Okres przechowywania
              </h2>
              <div className={s.tx}>
                <p>
                  Dane przechowujemy do czasu wycofania zgody, nie dłużej jednak niż 3 lata od przesłania
                  zgłoszenia.
                </p>
              </div>
            </article>
            <article className={s.it}>
              <span aria-hidden="true" className={s.itNo}>
                6
              </span>
              <h2>
                <span className={s.srOnly}>6.</span>{" "}
                Odbiorcy danych
              </h2>
              <div className={s.tx}>
                <p>
                  Dane mogą być przekazywane podmiotom przetwarzającym je na zlecenie administratora (np.
                  dostawcom usług IT i hostingu), a — wyłącznie za Twoją wiedzą w ramach konkretnego procesu —
                  klientom, u których prowadzona jest rekrutacja.
                </p>
              </div>
            </article>
            <article className={s.it}>
              <span aria-hidden="true" className={s.itNo}>
                7
              </span>
              <h2>
                <span className={s.srOnly}>7.</span>{" "}
                Twoje prawa
              </h2>
              <div className={s.tx}>
                <ul>
                  <li>dostęp do danych i otrzymanie ich kopii,</li>
                  <li>sprostowanie, usunięcie lub ograniczenie przetwarzania danych,</li>
                  <li>przeniesienie danych,</li>
                  <li>
                    wycofanie zgody w dowolnym momencie — bez wpływu na zgodność z prawem przetwarzania
                    dokonanego przed jej wycofaniem,
                  </li>
                  <li>wniesienie skargi do Prezesa Urzędu Ochrony Danych Osobowych.</li>
                </ul>
              </div>
            </article>
            <article className={s.it}>
              <span aria-hidden="true" className={s.itNo}>
                8
              </span>
              <h2>
                <span className={s.srOnly}>8.</span>{" "}
                Dobrowolność
              </h2>
              <div className={s.tx}>
                <p>
                  Podanie danych jest dobrowolne, ale niezbędne do udziału w rekrutacji. Nie podejmujemy wobec
                  Ciebie decyzji opartych wyłącznie na zautomatyzowanym przetwarzaniu, które wywoływałyby
                  skutki prawne.
                </p>
              </div>
            </article>
            <p className={s.org}>B2B.NET S.A., {COMPANY_LEGAL_LINE}</p>
          </div>
        </section>
      </main>
    </SiteFrame>
  );
}
