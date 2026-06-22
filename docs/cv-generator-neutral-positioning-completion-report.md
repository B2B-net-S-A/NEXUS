# CV Generator — neutralne pozycjonowanie (bez wskazywania konkretnego klienta/projektu)

**Data:** 2026-06-22
**Plik zmieniony:** `backend/app/services/cv_generator_b2b/prompts.py`
**Zgłoszenie:** Generator tworzył w CV zbyt bezpośrednie sformułowania wiążące kompetencje
kandydata z konkretnym klientem/projektem.

## Problem

Przykład z produkcji (`/cv-generator`), sekcja „Dlaczego nasz kandydat":

> „Doświadczenie w analizie logów i monitorowaniu backendu przy użyciu **Kibany** –
> bezpośrednio odpowiadające potrzebom projektu dla **Credit Agricole Bank Polska**
> w obszarze bankowości **korporacyjnej**."

**Oczekiwane:** generator opisuje doświadczenie i kompetencje kandydata neutralnie, bez
bezpośredniego wskazywania, że dana umiejętność odpowiada potrzebom konkretnego klienta
lub projektu.

## Root cause

Nie był to „przypadek" modelu — robił dokładnie to, co kazał mu prompt systemowy.
Instrukcja **#7 (KONTEKST PROJEKTU KLIENTA / CLIENT PROJECT CONTEXT)** w `prompts.py`
explicite nakazywała:

> „ostatni punkt why_points powinien wiązać faktyczne doświadczenie kandydata z tym
> projektem (np. „Doświadczenie w [X] bezpośrednio odpowiada potrzebom projektu [Y]")".

Prześledzono całą ścieżkę generacji (`standalone_service.py` → `champion_builder.py` →
`docx_renderer.py`): `why_points`/`responsibilities`/`skills` pochodzą **wyłącznie** z JSON
zwróconego przez Claude; post-processing tylko **pogrubia** słowa MUST-HAVE/NICE-TO-HAVE i
koryguje dokładną liczbę lat. **Żaden kod nie wstrzykuje nazwy klienta** — sterownikiem jest
prompt. Nazwa klienta trafia do modelu przez `<champion_profile>` (`project_context.about` /
`selling_points`), a instrukcje #1–#7 zachęcały do jej użycia w treści.

## Zmiana (PL + EN, oba prompty)

1. **#7 przepisana** z „wiąż skill → nazwany projekt" na **pozycjonowanie-only**: kontekst
   projektu używany wyłącznie wewnętrznie (wybór/kolejność realnego doświadczenia); zakaz
   nazywania klienta/projektu/branży i fraz „odpowiada potrzebom / idealnie pasuje /
   dopasowany do" — z listą zakazanych sformułowań. Ostatni why_point opisuje realne
   doświadczenie **samodzielnie**.
2. **Reguła nadrzędna NEUTRALNOŚCI** dodana na początku sekcji Profilu Championa —
   subordynuje punkty 1–7: nigdy nie przenoś nazwy klienta/projektu/marki/branży do
   żadnego pola wyjściowego (`position`, `why_points`, `responsibilities`, `skills`), nie
   cytuj `<champion_profile>` dosłownie.
3. **#3 (obowiązki)** dociśnięte — „spójne z językiem klienta" → neutralna terminologia
   branżowa, nigdy nazwa klienta/projektu, bez cytowania Profilu Championa.
4. **#5 (insight konsultanta)** dociśnięte — użycie wyłącznie wewnętrzne, bez cytowania
   treści ani przenoszenia nazwy klienta/projektu.
5. **#6 (tytuł CV)** przebudowane — tytuł MUSI być zawsze ogólną, neutralną nazwą roli bez
   tokenu klienta/marki/branży (np. „Corporate Banking Security Analyst u [klient]" →
   „Security Analyst"); nomenklaturę klienta wolno przyjąć tylko gdy już jest takim
   neutralnym tytułem roli.

## Weryfikacja

- **Adversarialny audit (workflow, 2 agenty równolegle):** ścieżka kodu — `clean` (żaden
  kod nie buduje nazwy klienta do pól wyjściowych). Prompt — pierwszy przebieg wykrył 3
  residualne wektory (#6 tytuł, #3 obowiązki, #5 insight) mimo naprawy #7; wszystkie
  domknięte powyższymi zmianami. Re-audit potwierdził #3/#5/regułę nadrzędną jako CLOSED;
  #6 dodatkowo przebudowane tak, by twarde ograniczenie było na początku (bez sekwencji
  „pozwól-potem-usuń").
- **Content-check:** `get_prompt('pl'|'en')` + warianty blind ładują się poprawnie, JSON
  skeleton nienaruszony, stare dyrektywy usunięte, frazy „matches the needs" występują już
  tylko jako **zakazane przykłady**.
- **Testy:** żaden test nie asercjonował starego zachowania; `prompts.py` to czyste
  literały stringów (brak logiki). ruff/pytest lecą w CI.

## Znane ograniczenia / follow-up

- Weryfikacja end-to-end (realne wygenerowane CV) wymaga uploadu CV + Profilu Championa +
  wywołania Anthropic — zalecany spot-check jednego CV pod klienta po deployu.
- `#1 MUST-HAVE` nadal dodaje punkt „Posiada kluczowe technologie wymagane **na
  stanowisku**: [lista]" — to nazwy technologii kandydata + generyczna rola, nie nazwa
  klienta/projektu; świadomie zostawione (rdzeń wartości CV). Reguła nadrzędna i tak go
  obejmuje.
