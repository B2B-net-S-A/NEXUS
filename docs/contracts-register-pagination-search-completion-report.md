# Rejestr kontraktów klienta — paginacja + wyszukiwarka konsultanta

> PR #599 · branch `claude/naughty-sanderson-98a909`

## Problem

W zakładce **Kontrakty** po wybraniu klienta (np. *Nordea Bank Abp* — 329
kontraktów) rejestr renderował tylko pierwsze 100 rekordów (`page_size=100`
na sztywno, bez `page`) i nie miał pola wyszukiwania. Użytkownik **nie mógł
dotrzeć do rekordów spoza pierwszej strony** ani odfiltrować listy po
nazwisku konsultanta.

## Rozwiązanie (frontend + testy; backend bez zmian)

Zakres jest **frontendowy**: backend `GET /api/contracts` **już** ma parametr
`q` (full-text po imieniu/nazwisku kandydata + nazwie klienta + tytule
stanowiska, z normalizacją NFC — patrz `nexus-name-search-nfc`, PR #600/#606).
Rejestr klienta po prostu z niego nie korzystał. Ta zmiana go podpina i dokłada
paginację.

### Frontend — `ClientContractRegister.tsx`

- Stan `page` + kontrolki paginacji: **Poprzednia / Następna**, „Strona X z Y",
  `PAGE_SIZE=50`, `keepPreviousData` (React Query v5) dla płynnego przewijania
  bez migotania.
- Debounce'owane pole wyszukiwania (`FilterBar` + `useDebouncedValue`, 300 ms)
  wpięte w istniejący parametr `q`; placeholder „Szukaj po nazwisku konsultanta…".
- Zmiana frazy resetuje do strony 1; pusty wynik wyszukiwania ma własny
  komunikat (bez CTA „Dodaj pierwszy kontrakt").
- `queryKey` rejestru rozszerzony o `page` + `search` i **współdzielony** z
  optimistic update prolongaty (`ProlongationCell` dostaje go propem), żeby
  inline-edycja statusu przedłużenia trafiała we właściwy wpis cache.

### Backend — testy (kod bez zmian)

- `test_contracts_filters_multi.py`: 2 testy domykające kontrakt `q` od strony
  konsultanta (zawężenie po nazwisku + pełne „imię nazwisko" case-insensitive)
  — przechodzą na istniejącej implementacji `q` z main.

## Zmienione pliki

| Plik | Zmiana |
|---|---|
| `frontend/src/components/contracts/ClientContractRegister.tsx` | Paginacja + wyszukiwarka (wpięte w `q`) |
| `backend/tests/test_contracts_filters_multi.py` | 2 testy `q` po nazwisku konsultanta |

> Uwaga historyczna: pierwotny szkic dokładał własny parametr `q` w
> `list_contracts`, ale main dorobił już bogatszy `q` (NFC + klient + stanowisko)
> w PR #600/#606, więc backend zostaje nietknięty — żeby nie dublować parametru.

## Weryfikacja

- Frontend: `tsc --noEmit` ✓ · `next lint` ✓ (exit 0, plik bez ostrzeżeń).
- Backend: `ruff check` ✓ (testy) · pytest **w CI** (`Backend (ruff + pytest)`).
- **UI smoke (lokalnie, harness `/preview/*` + Preview MCP, mock 120 rekordów):**
  paginacja „Strona 1 z 3" (50/stronę) → „Następna" → strona 2 zaczyna od
  NRD-0051, „Poprzednia" się włącza; wyszukiwarka „Kowalski" zawęża 120 → 12
  (wszystkie wiersze = *Kowalski*), licznik się aktualizuje, pasek paginacji
  znika przy ≤1 stronie; zero błędów w konsoli.

## Znane ograniczenia / follow-up

- **UI smoke** — zweryfikowane lokalnie na mockach. Na prod po merge + deploy
  warto potwierdzić na realnych danych (Nordea Bank Abp, 329 kontraktów).
