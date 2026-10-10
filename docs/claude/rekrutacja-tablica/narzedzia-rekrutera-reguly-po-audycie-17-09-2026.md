# Narzędzia rekrutera — reguły po audycie 17.09.2026

<!-- indeks: HoR = parytet z rekruterem, stawka do klienta, werdykt HM, kalendarz, powiadomienia z triggerów -->

Audyt `docs/recruiter-tools-audit-2026-09-17.md`, raport z poprawek
`docs/recruiter-tools-fixes-completion-report.md`. Decyzje Artura, które łatwo
cofnąć „przy okazji”:

- **Bramka „Pending” USUNIĘTA** (wyłączona 17.09.2026, kod skasowany 18.09.2026
  — szczegóły w sekcji „Kanban bez bramek”). Ruch na „Zweryfikowany” ze stawką
  ponad budżet przechodzi jako `active`, a przekroczenie jedzie na kartę jako
  informacja (`budget_exceeded`, odznaka „ponad budżet”). Trasy akceptacji /
  odrzucenia i `/pending-verifications` nie istnieją, UI kolejki usunięte
  (`/pending-verifications` → 308 na `/jobs`, bo stare powiadomienia w bazie
  nadal tam linkują). Stare wiersze `pending` zalicza jednorazowo
  `pending_verification_promotion.py` (blok w `entrypoint.sh`, znacznik
  `pending_verification_promotion_2026_09_17`): status `active`
  + `record_accepted_verification`, `approved_by` puste.
- **Head of Recruitment = parytet z rekruterem.** HoR jest w `RecruiterPlus`,
  `CANDIDATE_WRITE_ROLES` i zbiorach `recruitment_access` (ruchy, notatki,
  przypisania, pliki, kalendarz). Front bramkuje zapis na profilu capability
  `candidate.write` (lustro `CandidateWriteAccess`), nie samą sekcją. HoR nadpisuje
  cudze werdykty HM i feedback z rozmów (jak DL). W kalendarzu HoR edytuje cudze
  wydarzenia, ale **odwołać/usunąć** (także PATCH `status=cancelled`) może tylko
  właściciel albo admin — `user_can_remove_event`, flaga `can_remove` w odpowiedzi.
- **Stawka do klienta** (`PATCH …/client-rate`): od 23.09.2026 wyłącznie
  admin i Delivery Lead (sekcja „Rekrutacje i kandydatów widzą wszyscy”).
  Jedna funkcja `resolve_client_rate_write` zasila bramkę i
  `can_write_client_rate` w `GET /api/jobs/{id}`; tablica i warsztat CV pytają
  o stawkę tylko przy `true`.
- **Wyszukiwarka, tryb semantyczny:** sort i chipy „podbijające ranking” działają
  też w hybrydzie (`_resort_hybrid_pool`: soft-ranki → sort → pozycja RRF). Bez
  chipów i przy „Trafność” kolejność RRF zostaje nietknięta.
- **Werdykt HM z karty rekrutacji zapisuje WYŁĄCZNIE wiersz bez wydarzenia.**
  Wiersz przypięty do rozmowy opisuje tę rozmowę, a FK ma `ON DELETE CASCADE`
  — nadpisanie go gubiło notatkę rundy 1 i kasowało werdykt z karty razem ze
  spotkaniem. Lista pokazuje ostatnio zmieniony wiersz pary (`updated_at`).
- **Kalendarz:** wydarzenia z Outlooka się ODWOŁUJE (`POST …/cancel`, Graph
  cancel → fallback DELETE), a `DELETE` na nich daje 409; `isAllDay`/iCal `DATE`
  → `all_day` (poza kolizjami, przypomnieniami i pasami siatki); przypomnienie
  czyta `reminder_minutes` i linkuje `/calendar?event=`. Picker rekrutacji
  w kalendarzu auto-wybiera i udostępnia tylko rekrutacje z `can_schedule`
  (członkostwo) — cudza podstawiona sama kończyła zapis 403.
- **Powiadomienia:** `stage_stuck_7d` tylko opublikowane rekrutacje, etap 7–30 dni,
  raz na tydzień per etap, z nazwiskiem i etykietą; resurface porównuje dobę
  Warsaw jak `ix_notif_dedup_daily` i zapisuje w savepoincie; `own_unread_count`
  steruje „Oznacz wszystko” (oznacza tylko własne); odświeżenia dzwonka po
  wiadomościach czatu są zlewane (`CHAT_REFRESH_COALESCE_MS`).
- **Powiadomienie z triggera ma JEDNĄ bramkę odbiorcy i JEDEN helper
  rekrutacji (od 18.09.2026).** `emit()` w `notification_triggers.py` pyta
  `notification_recipient_has_access` (`is_active` + polityka sekcji) — to
  jedyne wąskie gardło wszystkich producentów, więc nowy trigger nie ma jak go
  obejść; sprawdzanie per trigger rozjeżdża się przy pierwszym dopisanym.
  Mierzone przed zmianą: 10,5% powiadomień z 90 dni szło na konta NIEAKTYWNE
  (`stage_stuck_7d` w 30 dni: 1 701 do 4 kont nieaktywnych vs 903 do 3
  aktywnych), a konta dezaktywowane odtwarza nocny sync Traffita i nadal bywają
  właścicielami rekrutacji, więc to się nie naprawiało samo. Konsekwencja:
  **typ spoza `NOTIFICATION_SECTION_BY_TYPE` jest teraz odrzucany przy ZAPISIE**
  (dotąd zapisywał się i był niewidoczny dopiero przy odczycie) — pilnuje tego
  kontrakt w `test_notification_fanout.py`. Rekrutacje czyta wyłącznie
  `_open_jobs_by_id` (`status == published`); nieprzefiltrowany `_jobs_by_id`
  USUNIĘTY, bo to rozwidlenie było przyczyną: poprawka z 17.09 objęła jedną
  z dwóch gałęzi i `dl_stage_stale_6h` uzbierał 52 263 powiadomienia, z tego
  59,3% o rekrutacjach ZAMKNIĘTYCH, przeczytane: 1.
- **`GET /api/cv-generator/clients/{id}/rule-for-generation`** (bramka
  `CandidateWriteAccess`) zwraca notatkę i instrukcje DL tylko przy
  `can_view_knowledge` klienta — reszta roli dostaje same wymogi formularza.
- **Etykiety dostępności w wyszukiwarce** idą z `lib/search-availability.ts`
  („Otwarty na oferty”), nie z `lib/filter-options.ts` („Otwarty na projekty”).
