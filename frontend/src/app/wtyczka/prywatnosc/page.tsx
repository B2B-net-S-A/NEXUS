import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Polityka prywatności wtyczki LinkedIn | NEXUS",
  description: "Jak rozszerzenie NEXUS — LinkedIn przetwarza dane i jak odłączyć dostęp.",
};

export default function ExtensionPrivacyPage() {
  return (
    <main className="min-h-dvh bg-background px-5 py-10 text-foreground sm:px-8 sm:py-16">
      <article className="mx-auto max-w-3xl space-y-8 text-base leading-7">
        <header className="space-y-4 border-b border-border pb-8">
          <Link href="/" className="text-sm font-semibold tracking-wide text-primary">NEXUS</Link>
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
            Polityka prywatności wtyczki LinkedIn
          </h1>
          <p className="text-sm text-muted-foreground">
            Rozszerzenie „NEXUS — LinkedIn” · aktualizacja: 28 października 2026
          </p>
          <p>
            Wtyczka pomaga uprawnionym osobom z zespołu B2B Network sprawdzać
            profile w NEXUSIE i prowadzić rekrutacje. Ta strona opisuje dane
            przetwarzane przy korzystaniu z rozszerzenia.
          </p>
        </header>

        <section aria-labelledby="privacy-controller" className="space-y-3">
          <h2 id="privacy-controller" className="text-xl font-semibold">1. Administrator i kontakt</h2>
          <p>
            Administratorem danych w procesach rekrutacyjnych B2B Network jest
            B2B.net S.A., Aleje Jerozolimskie 180, 02-486 Warszawa.
            W sprawach danych osobowych można napisać do Inspektora Ochrony
            Danych: <a className="text-primary underline underline-offset-4" href="mailto:IOD@b2bnetwork.pl">IOD@b2bnetwork.pl</a>.
          </p>
          <p>
            Informacje o zasadach przetwarzania danych w organizacji zawiera też{" "}
            <a className="text-primary underline underline-offset-4" href="https://b2bnetwork.pl/polityka-prywatnosci/">
              polityka prywatności B2B Network
            </a>.
          </p>
        </section>

        <section aria-labelledby="privacy-data" className="space-y-3">
          <h2 id="privacy-data" className="text-xl font-semibold">2. Jakie dane są przetwarzane</h2>
          <ul className="list-disc space-y-2 pl-6">
            <li>
              Dane z otwartej strony LinkedIna lub LinkedIn Recruitera: imię
              i nazwisko, link do profilu, nagłówek, lokalizacja, obecna firma
              i stanowisko, doświadczenie zawodowe, umiejętności i opis profilu
              — o ile są dostępne na stronie. Przy sprawdzaniu listy osób:
              nazwisko, link, nagłówek i firma.
            </li>
            <li>
              Dane wpisane lub wybrane przez użytkownika: rekrutacje, notatki,
              zapis kontaktu i przypomnienie oraz dobrowolnie przesłany PDF
              profilu, w tym dane kontaktowe zawarte w dokumencie.
            </li>
            <li>
              Dane zwracane z NEXUSA zgodnie z uprawnieniami użytkownika, np.
              opiekun osoby, historia procesów i kontaktów, stawka,
              status zgody na przetwarzanie danych oraz informacje
              o ograniczeniach kontaktu z kandydatem.
            </li>
            <li>
              Dane połączenia: indywidualny klucz dostępu do rozszerzenia,
              identyfikator i wersja wtyczki, konto użytkownika, czas połączenia
              i użycia oraz liczniki odczytów i dodanych osób.
            </li>
          </ul>
          <p>
            Wtyczka nie pobiera hasła do NEXUSA ani danych logowania do LinkedIna.
            Nie odczytuje skrzynki wiadomości, plików cookies ani historii
            przeglądania innych stron.
          </p>
        </section>

        <section aria-labelledby="privacy-reading" className="space-y-3">
          <h2 id="privacy-reading" className="text-xl font-semibold">3. Kiedy i w jakim celu czytamy stronę</h2>
          <p>
            Gdy użytkownik korzysta z otwartego panelu bocznego, wtyczka
            odczytuje aktywny profil i sprawdza go w NEXUSIE. Zmiana aktywnej
            karty lub przejście do innego profilu przy otwartym panelu może
            wywołać kolejny odczyt. Sprawdzenie listy wyników wymaga kliknięcia
            przycisku w panelu. Wtyczka nie otwiera kolejnych profili w tle.
          </p>
          <p>
            Dane służą rozpoznaniu osoby w bazie, pokazaniu jej historii
            i ograniczeń kontaktu, podpowiedziom rekrutacji oraz operacjom
            wybranym przez rekrutera. Dodanie lub aktualizacja osoby, notatka,
            przypisanie do rekrutacji i zapis kontaktu wymagają działania
            użytkownika. Wtyczka nie wysyła wiadomości ani zaproszeń na LinkedInie.
          </p>
        </section>

        <section aria-labelledby="privacy-recipients" className="space-y-3">
          <h2 id="privacy-recipients" className="text-xl font-semibold">4. Przekazywanie danych i funkcje AI</h2>
          <p>
            Rozszerzenie przekazuje dane do serwera NEXUS powiązanego z kontem
            użytkownika przez szyfrowane połączenie HTTPS. Wyjątkiem jest
            wybrany przez użytkownika lokalny serwer testowy na własnym
            komputerze, z którym połączenie może używać HTTP. Dostęp w NEXUSIE
            mają osoby uprawnione w organizacji oraz dostawcy obsługujący
            system w zakresie potrzebnym do świadczenia usług.
          </p>
          <p>
            Podpowiedzi dopasowania mogą korzystać z usługi Voyage AI:
            serwer przekazuje tekst zawodowy z profilu w celu obliczenia
            podobieństwa do rekrutacji. Na żądanie użytkownika serwer może
            przekazać imię, wybrane informacje zawodowe z profilu i dane
            rekrutacji oraz podpis rekrutera do dostawcy modelu językowego
            skonfigurowanego w NEXUSIE, aby przygotować szkic wiadomości.
            Rekruter sprawdza i wysyła wiadomość samodzielnie. Podpowiedzi
            nie podejmują decyzji rekrutacyjnych.
          </p>
          <p>
            Przesłany PDF trafia do standardowego przetwarzania dokumentów
            kandydatów w NEXUSIE. Może ono odczytywać dane zawodowe i kontaktowe
            z dokumentu oraz korzystać z dostawców AI skonfigurowanych
            w systemie do analizy jego treści.
          </p>
          <p>
            Wtyczka nie sprzedaje danych, nie udostępnia ich reklamodawcom
            i nie zawiera narzędzi analitycznych ani reklamowych.
          </p>
        </section>

        <section aria-labelledby="privacy-storage" className="space-y-3">
          <h2 id="privacy-storage" className="text-xl font-semibold">5. Przechowywanie i bezpieczeństwo</h2>
          <p>
            W lokalnej pamięci rozszerzenia w przeglądarce
            ({" "}<code>chrome.storage.local</code>) zapisujemy klucz
            połączenia, adresy serwera i NEXUSA, datę połączenia oraz wybór
            serwera. Dane profili i wyniki sprawdzenia pozostają w pamięci
            otwartego panelu; nie są zapisywane w tej pamięci trwałej.
          </p>
          <p>
            Klucz daje dostęp wyłącznie do API rozszerzenia w granicach
            uprawnień użytkownika. Wygasa zgodnie z konfiguracją serwera;
            administrator może odwołać połączenie. Nowe połączenie tej samej
            osoby odwołuje poprzednie. Należy chronić profil przeglądarki
            i urządzenie przed dostępem innych osób.
          </p>
          <p>
            Dane zapisane w NEXUSIE, w tym kandydaci, notatki i dokumenty,
            podlegają zasadom retencji i obsługi praw osób w organizacji.
            Odłączenie lub usunięcie wtyczki nie usuwa tych rekordów z NEXUSA.
          </p>
        </section>

        <section aria-labelledby="privacy-control" className="space-y-3">
          <h2 id="privacy-control" className="text-xl font-semibold">6. Odłączenie i prawa osób</h2>
          <p>
            Opcja „Odłącz” w panelu usuwa klucz z tej przeglądarki.
            Odinstalowanie rozszerzenia usuwa jego lokalną pamięć.
            Aby odwołać klucz także na serwerze, należy skontaktować się
            z administratorem NEXUSA, który zarządza połączeniami w Ustawieniach.
          </p>
          <p>
            W sprawie dostępu do danych, ich sprostowania, usunięcia,
            ograniczenia przetwarzania, sprzeciwu lub innych przysługujących
            praw należy skontaktować się z Inspektorem Ochrony Danych pod
            adresem podanym wyżej. Zakres realizacji żądania zależy od podstawy
            i okoliczności przetwarzania danych.
          </p>
        </section>

        <footer className="border-t border-border pt-6 text-sm text-muted-foreground">
          Aktualną wersję polityki publikujemy na tej stronie z datą aktualizacji.
        </footer>
      </article>
    </main>
  );
}
