# „Prowadzi” — przypisanie osoby prowadzącej kandydata w rekrutacji
<!-- indeks: admin i HoR przypisują, osoba z rolą rekrutera (też DL), `candidate_job_owners`, karta, Moi ludzie, Liga, premia -->

Prośba Olafa z 23.10.2026 (Jacek Z. w rekrutacji 324353 był na karcie
Zuzanny, a prowadziła go Marlena). Decyzje Artura z 25.10.2026, makiety:
https://claude.ai/artifact/RYRUWbkuSfYWnW2NfJ6FUu.

- **Kto przypisuje:** admin i Head of Recruitment (`HeadOfRecruitmentPlus`,
  `PUT /api/pipeline/jobs/{job_id}/candidates/{candidate_id}/owner`). Delivery
  Lead i rekruter widzą wiersz „Prowadzi” w nagłówku panelu osoby bez
  przycisku. Powód jest obowiązkowy (3–500 znaków).
- **Kogo można przypisać:** aktywną osobę z rolą rekrutera — główną albo
  dodatkową, także Delivery Leada, który rekrutuje (`pair_owner.can_own`).
  Sam DL bez roli rekrutera nie jest na liście, a serwer odpowiada 422.
- **Co przechodzi na przypisaną osobę** (jedna osoba wszędzie, nie da się
  przenieść części):
  - karta na Tablicy i panel (`owner_*` w odpowiedzi Tablicy, `cardOwner`
    rola `assigned` w każdej kolumnie), „kto ma ruch” (`recruiter_id` karty);
  - filtr „Kto dodał” i kolejka panelu (`board-added-by.adderId`) — osoba
    od systemu z przypisaniem nie jest już „System”;
  - dzwonki i domyślny rekruter pary (`interview_slots.default_recruiter_ids`:
    przypisanie przed właścicielem procesu), follow-up po CV
    (`candidate_followups`), dzwonek „Match” (`dl_match._source_recruiter_id`);
  - „Moi ludzie” (`my_people._owned_pairs_cte`);
  - Liga Mistrzów, cele i KPI (`kpi_panel.VERIFIER_ANCHORED_CTE`,
    `credited_nexus`): wszystkie kamienie milowe pary. Zamrożone okresy Ligi
    się nie zmieniają (czytają migawkę);
  - premia rekrutera za placement (`placement_bonuses.load_verifiers`).
    Przypisany DL rekrutacji z rolą rekrutera dostaje obie premie (reguła D4
    z wyjątkiem z 25.10.2026, `dl-przesuwa-bez-blokad.md`). Premii już
    zatwierdzonej albo poprawionej przez Płace automat nie rusza.
- **Bez przypisania nic się nie zmienia:** prowadzi pierwszy weryfikujący,
  a przed weryfikacją osoba, która dodała.
- **Nie zmienia się:** historia etapów (kto co przesunął), „Zweryfikował(a)”
  w przeglądzie DL, Hall of Fame i tabele Insights „kto kliknął” — liczą
  osobę, która przesunęła etap (definicja D2), nie prowadzącą.
- **Dane:** `candidate_job_owners` (stan bieżący, klucz para) i
  `candidate_job_owner_events` (historia: komu, kto przypisał, kto był, powód).
  DDL w `services/pair_owner_schema.py` (migracja 0519 + lustro w
  `entrypoint.sh`), sonda w `/api/health/deep`. Przypisanie żyje na parze,
  nie na podejściu procesu — przetrwa ponowne otwarcie; przy zapisie dostaje
  je też bieżący otwarty proces (`owner_user_id`, `ownership_confirmed_*`).
  Korekcyjne usunięcie pary z rekrutacji zdejmuje przypisanie
  (`delete_voided_stage_history` → `pair_owner.forget_pair`), historia zostaje.
- **Lista osób w oknie** pochodzi z `/api/users/mentionable?include_inactive=true`
  (`useMentionableUsers` gubi `roles` i `is_active`, więc panel pyta wprost).
  Nieaktywne konto prowadzącego panel podpisuje „konto nieaktywne”.
- **Odejście z firmy (28.10.2026):** wyłączenie konta przypina „Prowadzi”
  żywych par do osoby, która odeszła (bez sprawdzania `can_own`), a parę
  domyka Delivery Lead jako opiekun — Liga, KPI i premia nie przechodzą na
  DL-a. → `odejscie-rekrutera-opieka-delivery-leada.md`
