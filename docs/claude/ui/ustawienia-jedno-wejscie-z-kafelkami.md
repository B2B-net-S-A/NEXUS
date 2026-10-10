# Ustawienia = jedno wejście z kafelkami (22.09.2026)

`/settings` to strona startowa z pięcioma obszarami (Moje konto · Zespół i
dostęp · Rekrutacja · Umowy i stawki · System) → lista pozycji obszaru → ekran.
Mapa i reguły widoczności: `frontend/src/lib/settings-registry.ts` (jedyne
źródło; czyta je też paleta ⌘K i `app/settings/layout.tsx`, który rysuje
ścieżkę „Ustawienia / Obszar / Pozycja" nad podstronami z własną trasą).
Widok wynika wyłącznie z adresu (`?area=`, `?item=`); stare `?tab=` mapuje
`LEGACY_SETTINGS_TABS` — nie usuwaj, linki są w bazie i w zakładkach.

- **Decyzja Artura:** raporty (LinkedIn, hiring managers, przegląd klientów,
  audyt czatów, podgląd importu), narzędzia techniczne (diagnostyka, API,
  System/Log/Import CV/Narzędzia w Administracji), Konflikty, Coaching, Pomoc
  i Teams zniknęły z menu. Pozycje `hidden: true` dalej otwierają się pod
  adresem (`?item=conflicts`, `?item=advanced` = dawna siatka „Zaawansowane").
- **„Słownik umiejętności" (`?item=skills`, obszar Rekrutacja, 23.09.2026)** to
  jedyna część Cortexa, która przeżyła jego usunięcie: dodanie umiejętności,
  aliasy i mapowanie nieznanych terminów (`api/skills_admin.py`,
  `HeadOfRecruitmentPlus` + zapis Sourcing; `services/skill_curation.py`
  odświeża `ALIAS_MAP` po każdym zapisie). Tabele `cortex_*` zostają (DROP
  osobną migracją); `cortex_unmatched_terms` już nie rośnie.
- Nowa pozycja = wpis w rejestrze z bramką (`gate`) lustrzaną do backendu
  i `case` w `SettingsItemBody` (albo `route` dla osobnej strony).
- `ownHeader` = komponent ma własny nagłówek; strona rysuje wtedy tylko ścieżkę.
