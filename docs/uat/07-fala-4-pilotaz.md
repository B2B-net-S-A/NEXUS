# 07 — Fala 4: pilotaż z ludźmi (≈ tydzień)

> AI sprawdziło, że system nie przeczy sam sobie. Ludzie sprawdzają, że mówi prawdę o firmie.

## 1. Kto (2–3 osoby, zgodnie z decyzją „kto zaczyna pierwszy”)

Domyślnie: 1 rekruter, 1 Delivery Lead z klientem wielo-konsultantowym, 1 osoba z Finansów.
Każda dostaje **jedną stronę** instrukcji (agent generuje z kart modułów swojej roli: trasy + 10 pytań kontrolnych).

## 2. Co robią

Prawdziwą pracę, na prawdziwych danych, w NEXUS-ie — RÓWNOLEGLE z dotychczasowym narzędziem
(chyba że decyzja o Trafficie = twarde cięcie). Codziennie 15 minut na formularz:

| Pytanie | Odpowiedź (tak/nie + komentarz) |
|---|---|
| Czy liczby, które widzisz (stawki, MRR, MD, liczba kandydatów), zgadzają się z tym, co wiesz z innych źródeł? Które nie? | |
| Czy zrobiłeś dziś coś w NEXUS-ie, co musiałeś potem poprawić ręcznie gdzie indziej? | |
| Czy jakiś ekran pokazał pustkę tam, gdzie spodziewałeś się danych? | |
| Czy dostałeś powiadomienie/alert, który był błędny lub zdublowany? | |
| Czy czegoś, co robisz codziennie, nie da się zrobić w NEXUS-ie? | |
| Ile minut zajęło Ci dziś to, co w starym narzędziu zajmowało X? | |

Formularz = plik w prywatnym kanale (nie repo). Agent codziennie rano zbiera odpowiedzi do
`wyniki/F4/dzien-N.md` i przekłada „nie” na zgłoszenia w formacie z `05-szablon-zgloszenia.md`.

## 3. Co robi agent w tle (codziennie, 30 min)

- Karta C (Sentry) w trybie ciągłym: nowe issue z `users ≥ 1` spoza testerów → natychmiast do człowieka.
- `/api/health` co godzinę; każde `degraded` z czasem.
- Sprawdza dane pilotażu pod kątem par z karty B (MRR klienta DL vs Rada; stawki konsultant vs kontrakt) — na PRAWDZIWYCH danych, tylko odczyt, raport BEZ kwot w repo (kwoty zostają w `wyniki/`).
- Nocny Playwright zielony? Backup drill (poniedziałek) zielony?

## 4. Kryteria zakończenia pilotażu = start produkcyjny

- [ ] 5 dni roboczych bez nowego P0/P1 od pilotów i z Sentry.
- [ ] Każdy pilot odpowiedział „tak” na pytanie 1 (liczby się zgadzają) w ostatnich 3 dniach — albo rozbieżność ma wyjaśnienie na piśmie (np. „ewidencja kontraktów młodsza niż firma”).
- [ ] Lista „nie da się zrobić w NEXUS-ie” pusta ALBO każdy punkt ma decyzję `defer-after-launch` z terminem.
- [ ] Backup drill zielony (BLOCKER z Fali 0).
- [ ] Decyzja o Trafficie wykonana (cięcie / równolegle N tyg. / zapis zwrotny) i zakomunikowana zespołowi.
- [ ] `docs/uat-completion-report-2026-09.md` uzupełniony sekcją „Pilotaż”.

## 5. Po starcie (pierwsze 2 tygodnie)

- Karta C dalej codziennie (agent), potem tygodniowo.
- Formularz z §2 tygodniowo dla całego zespołu (skrócony do 3 pytań).
- Zgłoszenia od zespołu → ten sam format → jeden PR na moduł tygodniowo.
