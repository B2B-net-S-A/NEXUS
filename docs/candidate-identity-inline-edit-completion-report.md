# Inline edycja danych kandydata (imię / nazwisko / e-mail / telefon)

> PR [#592](https://github.com/artur-t-96/Nexus/pull/592) · 2026-06-24

## Problem

**Jest:** Nie da się (w widoczny sposób) edytować imienia i nazwiska kandydata
z poziomu profilu.
**Ma być:** Da się ręcznie edytować imię, nazwisko, nr telefonu i e-mail.

Profil kandydata (`CandidateDetailV2`) nie eksponował żadnego oczywistego
sposobu na poprawę danych identyfikacyjnych:

- Edycja **istniała**, ale ukryta w `Więcej → Edytuj` → ciężki `EditCandidateModal`
  z ~20 polami.
- E-mail/telefon w nagłówku renderowały się **tylko gdy obecne** — dla kandydata
  zaimportowanego z Traffit jako `?` (brak sparsowanego imienia, brak kontaktu)
  nie było *żadnego* wejścia do uzupełnienia.

## Rozwiązanie (frontend-only)

Backend **nie wymagał zmian** — `PATCH /api/candidates/{id}` (`CandidateUpdate`)
akceptował `name`, `lastname`, `email`, `phone` od dawna.

- Widoczny przycisk **„Edytuj dane"** (ikona ołówka) w nagłówku profilu, obok
  badge'ów statusu.
- Otwiera lekki **inline-formularz** na 4 pola: Imię, Nazwisko, E-mail, Telefon
  + Zapisz/Anuluj — zamiast nawigacji do pełnego modala.
- Puste e-mail/telefon → `null` (czyszczenie; backend `EmailStr` odrzuca `""`).
- Walidacja: imię i nazwisko wymagane (spójnie z `EditCandidateModal`).
- Inline-edycja resetuje się przy przełączeniu kandydata (prev/next w drawerze).
- Po zapisie: invalidacja `["candidate", id]` + `["candidates-v2"]` (kafelki listy
  cache'ują imię/nazwisko).

## Pliki

| Plik | Zmiana |
|---|---|
| `frontend/src/components/v2/pages/CandidateIdentityEditor.tsx` | **nowy** — wyniesiony komponent inline-edytora (mały, testowalny) |
| `frontend/src/components/v2/pages/__tests__/CandidateIdentityEditor.test.tsx` | **nowy** — 3 testy (trim, empty→null, wymagane pola) |
| `frontend/src/components/v2/pages/CandidateDetailV2.tsx` | +28 — stan `editingIdentity`, reset na zmianę kandydata, przycisk „Edytuj dane", warunkowy render nagłówka |

## Weryfikacja

- `tsc --noEmit` — zielone
- `next lint` (nowe pliki) — bez ostrzeżeń/błędów
- `vitest run` — **191/191** (18 plików), w tym 3 nowe testy
- UI smoke przez Chrome po deployu (authed route — brak lokalnego `/preview/*`
  harnessu dla `CandidateDetailV2`)

## Znane ograniczenia / out-of-scope

- Pełny `EditCandidateModal` (`Więcej → Edytuj`) pozostaje bez zmian — inline-edytor
  to skrót do najczęstszej korekty, nie zamiennik.
- Inline-formularz nie waliduje formatu telefonu (spójnie z resztą aplikacji —
  telefon to wolny string; normalizacja last-9-digits dzieje się przy matchowaniu).
