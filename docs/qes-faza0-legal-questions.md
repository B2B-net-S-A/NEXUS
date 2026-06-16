[← powrót do docs/](./README.md)

# Faza 0 — pytania do prawnika / radcy prawnego (wdrożenie QES pod umowy B2B)

> Część planu [in-house-qes-signature-plan.md](./in-house-qes-signature-plan.md), Faza 0 (critical path). Gotowe do przekazania kancelarii.

**Projekt:** NEXUS (ATS) — własny moduł e-podpisu wbudowany w system rekrutacyjny B2B Network
**Cel dokumentu:** uzyskanie opinii prawnej przed budową/uruchomieniem modułu QES
**Data:** 2026-06-16

---

## 1. Kontekst projektu (dla kancelarii)

Budujemy **własny moduł e-podpisu wbudowany w nasz system NEXUS**, w pełni zastępujący dotychczasową platformę pośredniczącą (Autenti). Moduł będzie używany **wyłącznie** do podpisywania umów B2B generowanych w naszym Generatorze Umów B2B — umów zawieranych między **B2B Network** (spółka) a **konsultantem IT** (najczęściej osoba prowadząca jednoosobową działalność gospodarczą — JDG, rzadziej spółka).

**Założenie wyjściowe (do potwierdzenia w pyt. 1):** ponieważ umowy te przenoszą **majątkowe prawa autorskie**, a art. 53 ustawy o prawie autorskim i prawach pokrewnych wymaga dla takiego przeniesienia **formy pisemnej pod rygorem nieważności**, formę tę w postaci elektronicznej spełnia **wyłącznie podpis kwalifikowany (QES)** zgodnie z art. 78¹ k.c. Dlatego przyjmujemy **QES jako wymóg bezwzględny dla obu stron** każdej umowy (konsultant + imienny reprezentant spółki).

**Wybrana architektura techniczna (jeden dostawca — KIR):**

- **Pas główny:** KIR **Szafir SDK** (Web Module — biblioteka JS osadzona na naszej stronie `/sign` + lokalny Szafir Host). Podpis składany po stronie klienta (client-side) kartą / tokenem / certyfikatem mobilnym podpisującego, w formacie **PAdES**. Szafir obsługuje certyfikat dowolnego kwalifikowanego dostawcy usług zaufania (QTSP).
- **Pas zapasowy:** KIR **mSzafir „One Shot"** (chmura) — **jednorazowy certyfikat kwalifikowany** dla konsultanta nieposiadającego własnego certyfikatu; tożsamość potwierdzana przez bankowość / mObywatel / e-dowód, podpis składany w chmurze przez API mSzafir.
- **Strona spółki:** imienny reprezentant B2B Network podpisuje **kartą** przez ten sam Szafir.
- **Walidacja po naszej stronie:** biblioteki **pyHanko** + **EU DSS** w oparciu o europejskie **listy zaufania (Trusted List)**. Docelowy poziom: **PAdES B-LT**, archiwalnie **B-LTA**, z kwalifikowanym **znacznikiem czasu (TSA)**.
- **Stos technologiczny:** backend Python/FastAPI, frontend Next.js.

Poniższe pytania mają na celu potwierdzenie poprawności tych założeń i wskazanie ewentualnych dodatkowych wymogów, które musimy odwzorować w logice systemu.

---

## 2. Pytania

### Pytanie 1 — Forma pisemna a QES przy przeniesieniu praw autorskich

Czy nasz szablon umowy B2B (generowany w systemie i renderowany do pliku PDF), podpisany **dwustronnie podpisem kwalifikowanym (QES)** — przez konsultanta oraz imiennego reprezentanta spółki — **skutecznie zachowuje formę pisemną wymaganą przez art. 53 pr.aut.** dla przeniesienia majątkowych praw autorskich (poprzez równoważność z formy elektronicznej z art. 78¹ k.c.)? Czy istnieją **dodatkowe wymogi co do treści klauzuli IP** (np. wyraźne wskazanie pól eksploatacji, moment przejścia praw, prawa zależne, nośniki, utwory przyszłe), bez których przeniesienie będzie nieskuteczne mimo prawidłowego podpisu?

> **Dlaczego to ważne dla wdrożenia:** to fundament całego projektu — jeśli QES dwustronny nie wystarcza albo szablon wymaga konkretnych klauzul, musimy to zaszyć w samym Generatorze Umów B2B (treść + walidacja obecności klauzul), zanim w ogóle dopuścimy umowę do podpisu. Błąd tutaj unieważnia każdą zawartą umowę.

### Pytanie 2 — Reprezentacja spółki (strona B2B Network)

Jak **prawidłowo umocować osobę podpisującą po stronie B2B Network**: czy wystarczy członek zarządu zgodnie z reprezentacją ujawnioną w KRS, czy dopuszczalne (i bezpieczniejsze) jest **pełnomocnictwo** dla wyznaczonego pracownika? Czy przy obowiązującej w spółce **reprezentacji łącznej** jeden podpis QES jest niewystarczający i potrzebujemy **dwóch imiennych podpisów**? Czy podpis złożony **certyfikatem imiennym osoby fizycznej** (karta) jest z punktu widzenia reprezentacji wystarczający?

> **Dlaczego to ważne dla wdrożenia:** od tego zależy logika „kto po naszej stronie podpisuje". Jeśli wymagana jest reprezentacja łączna lub pełnomocnictwo, system musi wymusić **dwa podpisy** lub **załączenie/weryfikację pełnomocnictwa** zanim umowa stanie się skuteczna — inaczej generujemy wadliwe umowy seryjnie.

### Pytanie 3 — Strona konsultanta: JDG vs spółka

Gdy konsultant działa jako **JDG**, umowę podpisuje właściciel działalności. Gdy konsultant działa jako **spółka** (np. sp. z o.o.) — **kto musi podpisać** zgodnie z reprezentacją ujawnioną w KRS i czy może tu również wystąpić reprezentacja łączna? **Jak powinniśmy weryfikować i dokumentować** umocowanie podpisującego po stronie konsultanta (np. odpis KRS/CEIDG na moment podpisu, oświadczenie o umocowaniu), aby w razie sporu wykazać, że umowa została zawarta prawidłowo?

> **Dlaczego to ważne dla wdrożenia:** musimy w systemie rozróżnić **dwie ścieżki kontrahenta** (JDG vs spółka) i ewentualnie wymagać innej liczby podpisów oraz innego zestawu dokumentów weryfikacyjnych. Określi to model danych (typ kontrahenta) i checklistę przed dopuszczeniem do podpisu.

### Pytanie 4 — Kwalifikowana pieczęć elektroniczna a podpis osoby fizycznej

Prosimy o **jednoznaczne potwierdzenie**, że **kwalifikowana pieczęć elektroniczna** (przypisana do podmiotu/spółki, nie do osoby) **NIE zastępuje podpisu osoby fizycznej** przy składaniu oświadczenia woli przenoszącego prawa autorskie — tzn. że pod taką umową musi widnieć **podpis kwalifikowany imiennej osoby fizycznej**, a nie pieczęć podmiotu.

> **Dlaczego to ważne dla wdrożenia:** technicznie pieczęć podmiotu byłaby wygodniejsza (jeden „firmowy" certyfikat, brak kart imiennych). Musimy wiedzieć z całą pewnością, że **tej drogi nie wolno użyć** dla tych umów, żeby nie zaprojektować modułu wokół rozwiązania, które unieważnia umowy.

### Pytanie 5 — Podpisujący-obcokrajowiec (UE i spoza UE)

Konsultant z **innego kraju UE**, bez polskiego PESEL i bez dostępu do polskiej bankowości — czy jego **własny unijny certyfikat kwalifikowany** (zgodny z eIDAS, np. na karcie) jest w Polsce **w pełni równoważny** polskiemu QES dla zachowania formy pisemnej, i czy są tu istotne ryzyka (np. zakres pól eksploatacji wg innego prawa, język umowy, prawo właściwe)? Jak należy podejść do konsultanta **spoza UE** (np. brak eIDAS — czy taki podpis może być uznany za QES, czy potrzebne jest inne rozwiązanie / inna forma)?

> **Dlaczego to ważne dla wdrożenia:** pas zapasowy mSzafir „One Shot" opiera się na polskiej identyfikacji (bank/mObywatel/e-dowód), więc dla obcokrajowca jest **niedostępny**. Musimy wiedzieć, czy honorujemy unijny certyfikat na karcie (pas główny Szafir to obsłuży technicznie), oraz czy dla osób spoza UE w ogóle wolno dopuścić podpis elektroniczny, czy trzeba uruchomić ścieżkę alternatywną (np. papier).

### Pytanie 6 — Walidacja i wartość dowodowa

Czy przechowywanie po naszej stronie **wyniku walidacji** (raport „is QES" z EU DSS w oparciu o Trusted List) wraz z plikiem PDF w formacie **PAdES B-LT / B-LTA** (z kwalifikowanym znacznikiem czasu) stanowi **wystarczający dowód zachowania formy** i ważności podpisu na wypadek sporu lub kontroli? Jaki **okres retencji** rekomendujecie i czy dla umów przenoszących prawa autorskie (potencjalnie bardzo długi horyzont) należy **bezwzględnie stosować B-LTA** (archiwizacja długoterminowa z odświeżaniem znaczników), czy wystarcza B-LT?

> **Dlaczego to ważne dla wdrożenia:** to determinuje, **co i jak długo musimy przechowywać** (sam PDF, raport walidacji, materiał dowodowy LTV) oraz czy budujemy mechanizm **odświeżania znaczników czasu (B-LTA)** dla długoterminowej weryfikowalności. Wpływa na schemat bazy, storage i procesy archiwizacyjne.

### Pytanie 7 — mSzafir „One Shot": czy to pełnoprawny QES

Prosimy o **potwierdzenie**, że **jednorazowy certyfikat kwalifikowany mSzafir** (wydawany „na chwilę" złożenia podpisu, po identyfikacji tożsamości przez bank/mObywatel/e-dowód) skutkuje **podpisem kwalifikowanym (QES) równoważnym formie pisemnej** — a **nie** jedynie podpisem zaawansowanym (AdES). Czy są jakiekolwiek ograniczenia lub warunki, przy których ten podpis **nie** byłby uznany za QES (np. wadliwa identyfikacja, brak określonych danych)?

> **Dlaczego to ważne dla wdrożenia:** cały sens pasa zapasowego polega na tym, że konsultant **bez własnego certyfikatu** może podpisać umowę przenoszącą prawa. Jeśli „One Shot" to w istocie AdES, a nie QES, **forma pisemna nie zostaje zachowana** i pas zapasowy jest bezużyteczny dla tych umów — musielibyśmy go usunąć lub zastąpić.

### Pytanie 8 — RODO: powierzenie i zakres przetwarzania

Dane identyfikacyjne podpisującego (pozyskiwane przy ścieżce mSzafir z **banku / mObywatela / e-dowodu**) są przetwarzane przez **KIR** w toku procesu podpisu. **Jaki status pełni KIR** (procesor/podmiot przetwarzający czy odrębny administrator) i **jakie umowy/zapisy powierzenia** (DPA) są po naszej stronie niezbędne? Które dane podpisującego **możemy, a których nie wolno nam** przechowywać po naszej stronie po zakończeniu podpisu (np. dane z dowodu/mObywatela, numer PESEL, wizerunek), oraz jakie informacje należy podać podpisującemu (obowiązek informacyjny, podstawa prawna, okres przechowywania)?

> **Dlaczego to ważne dla wdrożenia:** od tego zależy, **co osadzamy w bazie i logach NEXUS**, a co zostaje wyłącznie po stronie KIR. Musimy poprawnie skonfigurować zakres pobieranych/zapisywanych danych, podpisać właściwe DPA z KIR oraz przygotować klauzulę informacyjną w UI `/sign` — błąd to ryzyko naruszenia RODO i kar.

---

## 3. Podsumowanie zależności technicznych (dla kontekstu)

| Pytanie | Co od odpowiedzi zależy w systemie |
|---|---|
| 1 | Treść szablonu + walidacja obecności klauzul IP; wymóg 2 podpisów QES |
| 2 | Logika „kto po stronie spółki podpisuje"; wymuszenie 2 podpisów / pełnomocnictwa |
| 3 | Rozróżnienie ścieżki JDG vs spółka; checklista dokumentów kontrahenta |
| 4 | Wykluczenie pieczęci podmiotu; wymóg certyfikatu imiennego osoby |
| 5 | Dostępność pasa mSzafir tylko dla PL; obsługa unijnej karty; ścieżka spoza UE |
| 6 | Zakres i okres retencji; budowa mechanizmu B-LTA (odświeżanie TSA) |
| 7 | Zasadność istnienia pasa zapasowego (One Shot = QES czy AdES) |
| 8 | Zakres danych w bazie/logach NEXUS; DPA z KIR; klauzula informacyjna w UI |

---

*Dokument przygotowany do przekazania kancelarii. Prosimy o wskazanie ewentualnych dodatkowych obszarów ryzyka, których nie ujęto powyżej, a które są istotne dla zgodnego z prawem wdrożenia własnego modułu QES pod umowy B2B przenoszące prawa autorskie.*
