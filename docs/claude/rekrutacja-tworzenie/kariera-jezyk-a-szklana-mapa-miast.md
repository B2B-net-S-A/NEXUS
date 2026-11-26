# Strona kariery: język A — szklana mapa miast (decyzja Artura 26.11.2026)

Artur nie lubił pierwszego ekranu kariera.b2bnetwork.pl (wielkie „101”
i przechylone karty miast). Z trzech kierunków (A mapa miast, B tablica
z klapkami, C płyty technologii) wybrał A, razem z makietami oferty i stanów
(kanwa https://claude.ai/artifact/MhVp7su2eP5CYi2U5YkbRA, strony „Pierwszy
ekran A” i „Oferta i kolejne ekrany (A)”). Zastępuje w
`strona-kariery-dla-kandydatow.md`: talię kart miast na liście, wielkie słowo
nad tytułem oferty i wymagania w prawej kolumnie nagłówka (P1 z 24.11.2026).

Jego zasady do każdej zmiany tych ekranów: grafiki szczegółowe (izometria,
szkło na czerwonym polu), nic „do kliknięcia, żeby zobaczyć”, ton prestiżowej
firmy technologicznej, a nie kontraktowni, każdy ekran działa na telefonie
390 px z tekstem ≥ 16 px (rysunki są ozdobą: drobne napisy w SVG tylko od
1280 px, niżej mapa z czterema największymi miastami i większymi etykietami).

Kod: geometria `lib/career/polandMap.ts` (testy `lib/career/__tests__/polandMap.test.ts`),
rysunki `components/career/site/GlassMap.tsx`, układ `site/glass.module.css`
(kolory nadal tylko z tokenów `site.module.css`, nowy token `--on-red-soft`
#FFE3DA, 5,1:1 na czerwieni).

Reguły, które łatwo cofnąć:
- **Liczby i miasta tylko z tablicy** (`GET /api/public/career/jobs` →
  `facetCounts`). Wysokość kolumny = 3,6 jednostki na ofertę jak na makiecie,
  ściśnięta, gdy największe miasto by nie weszło; jedna oferta = 6 jednostek.
  Położenia 20 miast z `jobCities` są w `CITY_GEO` (osiem z makiety co do
  piksela, Trójmiasto rozsunięte, reszta z tego samego rzutu). Miasto spoza
  listy nie ma kolumny, ale jest w opisie mapy dla czytnika i w chipach.
- **Etykieta nie wchodzi w cudzą kolumnę ani etykietę**: najpierw strona
  z makiety, potem bliżej kolumny, potem strona przeciwna; gdy nic nie pasuje,
  etykieta znika (liczba zostaje w chipie). Pilnuje test.
- **Mapa oferty** (`offerMapMode`): praca zdalna = cała płyta świeci
  („Zdalnie z całej Polski”); hybryda i biuro = podświetlone miasta oferty
  z podpisem z parametrów (`officeNote`: „biuro 1 dzień w tygodniu”);
  zamknięta = przerywany obrys (API zamkniętej nie daje parametrów, więc
  zwykle bez miasta); miasto, którego nie ma na mapie = bez mapy.
- **Treści bez nowych obietnic**: lead listy to zdanie z makiety z liczbą
  rekrutacji i liczbą miast z danych; zgody RODO bez zmian (makieta je
  skraca, strona nie); „Cztery kroki do startu” bierze liczbę i nazwy kroków
  z `processSteps`. „CV jest u Marka.” odmienia imię prostymi regułami
  (`atName`), imię, którego nie umie odmienić, daje „CV jest u nas.”.
- **Formularz bez nowych pól**: makieta pokazuje pole „LinkedIn lub GitHub”,
  „Twoja technologia” przy „Zostaw CV” i formularz „Przyspiesz rozmowę” po
  wysłaniu — API zgłoszeń ich nie przyjmuje (`website` to pułapka na boty),
  więc nie weszły. Dodanie = zmiana `POST /api/public/career/apply` i decyzja
  Artura, gdzie zapisać link.
- Szukajka na pierwszym ekranie filtruje listę na żywo, a „Pokaż N ofert”
  przewija do listy. Chipy miast nad listą zastępują talię kart.
