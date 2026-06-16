[← powrót do docs/](./README.md)

# Faza 0 — zapytanie do KIR (Szafir SDK + mSzafir One Shot)

> Część planu [in-house-qes-signature-plan.md](./in-house-qes-signature-plan.md), Faza 0 (critical path). Gotowe do wysłania po uzupełnieniu danych spółki/kontaktu w stopce. Adresy KIR potwierdzić przed wysłaniem.

---

Krajowa Izba Rozliczeniowa S.A.
Zespół Szafir / mSzafir (Podpis Elektroniczny)
ul. rtm. Witolda Pileckiego 65
02-781 Warszawa
kontakt: szafir@kir.pl / mszafir@kir.pl

**Dotyczy: zapytanie ofertowo-techniczne — integracja podpisu kwalifikowanego (QES) z autorskim systemem ATS**

Szanowni Państwo,

jesteśmy firmą **B2B Network** działającą w obszarze IT staffingu (kontraktowanie konsultantów IT, zwykle prowadzących JDG). Budujemy **własny moduł e-podpisu wbudowany bezpośrednio w nasz system rekrutacyjny NEXUS** — bez platformy pośredniczącej / agregatora — który ma w pełni zastąpić dotychczasowe rozwiązanie. Zakres jest wąski i jednoznaczny: podpisywanie **umów B2B** generowanych w naszym module, dwustronnie (konsultant IT + imienny reprezentant naszej spółki).

Z uwagi na to, że umowy przenoszą **majątkowe prawa autorskie**, wymagana jest forma pisemna pod rygorem nieważności (art. 53 pr. aut.), którą w postaci elektronicznej spełnia **wyłącznie podpis kwalifikowany — QES** (art. 78(1) k.c.). Dlatego interesuje nas wyłącznie wariant kwalifikowany i **jeden dostawca (KIR)** dla obu ścieżek. Wybraliśmy architekturę dwutorową:

- **Ścieżka główna — Szafir SDK (Web Module):** komponent JS osadzony na naszej stronie `/sign` + Szafir Host lokalnie u podpisującego; podpis kartą / tokenem / certyfikatem mobilnym po stronie klienta, format PAdES, zwrot podpisanego pliku do naszego backendu.
- **Ścieżka zapasowa — mSzafir „One Shot":** certyfikat jednorazowy w chmurze dla konsultanta **bez własnego certyfikatu**, z identyfikacją (bank / mObywatel / e-dowód), podpis przez API mSzafir.

Po naszej stronie walidację i archiwizację realizujemy samodzielnie (pyHanko + EU DSS / Trusted List); cel docelowy to **PAdES B-LT, archiwalnie B-LTA, z kwalifikowanym znacznikiem czasu (TSA)**. Backend: Python/FastAPI; frontend: Next.js.

Poniżej zestaw konkretnych pytań handlowych i technicznych.

---

## 1. Szafir SDK — Web Module (ścieżka główna)

**Licencjonowanie i model:**
1. Czy oferują Państwo licencję na **Szafir SDK Web Module** (biblioteka JavaScript do osadzenia na własnej stronie web) wraz z **Szafir Host**? Jaki jest model licencyjny (jednorazowy / roczny / per-deweloper / per-instancja / per-podpis)?
2. Czy licencja obejmuje produkcyjne wdrożenie komercyjne na naszej własnej domenie/aplikacji?

**Wsparcie naszego flow:**
3. Czy Web Module pozwala osadzić komponent podpisu **na naszej własnej stronie** (nie na stronie KIR), tj. użytkownik podpisuje w kontekście naszej aplikacji `/sign`?
4. Czy podpis odbywa się **w pełni po stronie klienta** (klucz prywatny nie opuszcza karty/tokena/urządzenia), a do naszego backendu wraca już gotowy, podpisany plik?
5. Jak wygląda zwrot artefaktu — czy otrzymujemy kompletny **podpisany PDF (PAdES)** w przeglądarce do odesłania na backend, czy strukturę podpisu do złożenia po naszej stronie?

**Formaty i znacznik czasu:**
6. Które poziomy PAdES wspiera SDK: **B-B / B-T / B-LT / B-LTA**? Czy B-LT/B-LTA da się uzyskać w SDK, czy doosadzenie OCSP/CRL + archiwizację realizujemy po naszej stronie?
7. Czy w ramach podpisu dostępny jest **kwalifikowany znacznik czasu (TSA)** KIR? Jak jest rozliczany (w cenie SDK / osobno / per-stempel)? Jaki jest URL/endpoint TSA i limity?

**Certyfikaty i kompatybilność:**
8. Czy Szafir Host odczytuje certyfikat **dowolnego QTSP** z karty/tokena (KIR, Asseco/Certum, EuroCert, PWPW/Sigillum, mObywatel), czy tylko certyfikaty KIR?
9. Jakie **przeglądarki i systemy operacyjne** są wspierane (Chrome/Edge/Firefox/Safari; Windows/macOS/Linux)? Czy działa to bez rozszerzeń przeglądarki, czy wymaga dedykowanego plug-inu?
10. Jak wygląda **dystrybucja i instalacja Szafir Host** po stronie podpisującego (instalator Win/macOS/Linux, wymagania, czy potrzebne uprawnienia administratora)? Czy jest tryb „silent"/MSI dla środowisk firmowych?

**Środowisko i materiały:**
11. Czy udostępniają Państwo **środowisko integracyjne/testowe (sandbox)** dla SDK?
12. Czy dostępna jest **dokumentacja deweloperska + przykłady kodu web/JS** (integracja komponentu, callbacki, obsługa błędów)?

---

## 2. mSzafir „One Shot" / mSzafir API (ścieżka zapasowa)

**Produkt i tożsamość:**
13. Czy oferują Państwo **certyfikat kwalifikowany jednorazowy („One Shot")** dla osoby fizycznej **bez własnego certyfikatu** — wystawiany na potrzeby jednego podpisu?
14. Jakie **metody potwierdzenia tożsamości** są dostępne i jakie jest ich realne pokrycie: przelew/identyfikacja bankowa (które banki?), **mObywatel**, **e-dowód (NFC)**, wideoweryfikacja? Czy dla obcokrajowca (konsultant spoza PL) jest ścieżka identyfikacji?

**API i integracja:**
15. Jaki jest **kształt API** (REST/JSON? inny protokół?) do inicjowania One Shot i złożenia podpisu w chmurze? Czy jest model „server-to-server" sterowany z naszego backendu?
16. Czy dostępny jest **sandbox mSzafir** oraz **dokumentacja API** z przykładami?
17. Jakie są **limity i ograniczenia**: maks. rozmiar PDF, dopuszczalne formaty wejścia, czas ważności certyfikatu One Shot, okno czasowe na dokończenie podpisu?

**Format i TSA:**
18. Czy podpis One Shot zwraca **PAdES** i czy zawiera **kwalifikowany znacznik czasu (TSA)** w standardzie?

**Rozliczenia (kluczowe dla nas):**
19. Jaki jest **model rozliczeń**: per podpis / pakiety / abonament? Jakie ceny progowe?
20. **Czy nadawca (my, B2B Network) może opłacić podpis za odbiorcę (konsultanta)?** Tzn. czy możemy przejąć koszt One Shot, tak aby konsultant nie ponosił żadnej opłaty? To dla nas warunek kluczowy ścieżki zapasowej.

---

## 3. Pytania wspólne / operacyjne (oba produkty)

21. **Cennik i model komercyjny** obu produktów (Szafir SDK + mSzafir API) — pełna lista pozycji (licencja, TSA, podpisy, wsparcie).
22. **Onboarding:** kroki i lead time — podpisanie umowy, wymagane KYC/dokumenty po naszej stronie, czas do dostępu do **sandboxa** i osobno do **produkcji**.
23. **SLA i wsparcie integracyjne:** parametry SLA produkcyjnego, kanał wsparcia w trakcie integracji, czasy reakcji.
24. Czy KIR przydziela **dedykowanego opiekuna technicznego / handlowego** na czas wdrożenia i później?
25. **Wymagania prawne/formalne po naszej stronie** (np. status podmiotu, dane do umowy, ewentualne wymogi dot. przetwarzania danych / podpowierzenia, RODO) — co musimy przygotować.

---

## 4. Prosimy o przesłanie

1. **Ofertę handlową** dla obu produktów (Szafir SDK Web Module + mSzafir „One Shot"/API), z cennikiem i progami.
2. **Dokumentację techniczną** obu produktów (specyfikacja SDK web/JS, specyfikacja API mSzafir, wymagania Szafir Host, opis poziomów PAdES i TSA).
3. **Dostęp do środowiska sandbox** (SDK + mSzafir) lub instrukcję, jak go uzyskać.
4. **Przykłady integracji web** (kod JS osadzenia komponentu podpisu + przykładowe wywołania API).
5. **Wzór/draft umowy** oraz listę wymaganych dokumentów do onboardingu.

Chętnie umówimy się też na krótkie **call techniczny** z Państwa zespołem, aby zweryfikować architekturę przed rozpoczęciem integracji. Z góry dziękuję za informację, który zespół KIR (handlowy / techniczny) prowadzi tego typu wdrożenia.

Z poważaniem,

**[Imię i nazwisko]**
[Stanowisko — np. CTO]
B2B Network
[e-mail] · [telefon]
[NIP / dane spółki]
