# Grafika posta na LinkedIn: „Mapa”, „Konkrety” i karuzela (decyzja Artura 27.11.2026)
<!-- indeks: zakładka „Post na LinkedIn” w „Udostępnij”, `LinkedInPostTab`, `ogPostCard.tsx`, trasa `kariera/r/[slug]/grafika-posta` (`?v=mapa|konkrety|karuzela&s=`), `…/grafika-posta/dane`, `lib/career/postGraphic.ts`, `carouselPdf.ts`, `mapLabelColumn` -->

Prośba Olafa z 27.11.2026: zespół nie wrzuca na LinkedIna samego linku, tylko
grafikę, a link do aplikacji daje w pierwszym komentarzu. Przy takim poście
podgląd linku (grafika OG 1200 × 630) się nie pokazuje, więc rekruterzy robili
obrazek sami. Artur wybrał z makiet (https://claude.ai/artifact/DWgcByxaTpoevs5XiEsrvZ,
dane stagingu) wszystkie trzy warianty: „Mapa” (domyślny), „Konkrety”
i karuzelę PDF.

Kod: kadry `components/career/ogPostCard.tsx` (satori, jak `ogMapCard.tsx`),
dane i treść `lib/career/postGraphic.ts`, odczyt na serwerze
`lib/career/postServer.ts`, trasy `app/kariera/r/[slug]/grafika-posta/route.tsx`
(PNG) i `…/dane/route.ts` (JSON dla zakładki), PDF `lib/career/carouselPdf.ts`,
zakładka `components/v2/career-share/LinkedInPostTab.tsx`. Harness:
`/preview/career-share`, przypadek 1a.

Reguły, które łatwo cofnąć:
- **Treść wyłącznie z publicznej odpowiedzi strony kariery** (opublikowana
  wersja opisu, `GET /api/public/career/r/<slug>`) i tablicy — bez klienta,
  stawki i nazwiska (samo imię rekrutera). Przełączniki „pokaż” obowiązują:
  ukryte wymagania, mile widziane, parametry i kroki procesu nie trafiają do
  grafiki, karuzeli ani treści posta. Zamknięta rekrutacja = 404 grafiki.
- **Grafika nie udaje przycisku.** Obrazka w poście nie da się kliknąć, więc
  zamiast „Wyślij CV →” stoi „Link do aplikacji w komentarzu ↓”.
- **Format 1080 × 1350 (4 : 5)**: największy kadr w feedzie na telefonie.
  Stopka z domeną kariery (`primaryCareerHost`), nie z hosta żądania — plik
  pobiera się z NEXUSA.
- **Treść posta to szablon bez modelu AI** (`postText`): „Nowa rekrutacja: …”,
  miejsce z podpisem biura, podtytuł, technologie z tablicy, „Link do aplikacji
  w pierwszym komentarzu ↓”, do czterech hashtagów + `#praca #b2b`. Adresu
  w treści nie ma (LinkedIn tnie zasięg postów z linkiem). Komentarz =
  „Aplikuj tutaj: <link rekrutera do tej rekrutacji>”, więc zgłoszenia z posta
  liczą się w „Wynikach” jak z każdego linku. Rekruter może poprawić treść
  w oknie — tej poprawki kontrola publikacji nie sprawdza i okno to mówi.
- **Zakładka działa dopiero przy działającej stronie i istniejącym linku**
  (tak jak „Kopiuj” w „Link do tej rekrutacji”); wcześniej odsyła do opisu albo
  do wygenerowania linku.
- **Karuzela**: slajdy tylko z treścią (`carouselSlides`: okładka, „Czym się
  zajmiesz”, „Czego szukamy”, proces albo „Jak aplikować”). PDF składa
  przeglądarka z PNG tras (JPEG w `/DCTDecode`), bez biblioteki i bez serwera.
- **Podgląd w oknie rysuje ten sam komponent** w przeglądarce z danych
  `…/grafika-posta/dane` (ta sama domena — bez CORS i bez liczenia wejścia
  linku); pobranie idzie po PNG z trasy.
- **Podpis mapy przy kilku miastach** stoi po lewej od skrajnie lewej
  podświetlonej kolumny albo po prawej od skrajnie prawej (`mapLabelColumn`),
  także w grafice OG — przy pierwszej kolumnie wchodził na sąsiednie.
- Poza zakresem: publikacja posta z NEXUSA przez API LinkedIna (wymaga
  aplikacji z zatwierdzonym dostępem; nie sprawdzone).
