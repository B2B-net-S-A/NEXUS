# Presence / Currently Viewing — Completion Report

**Commit:** `f0b716f` (branch `main`)
**Data:** 2026-04-24
**Zakres:** Profil kandydata + strona rekrutacji, scope MVP (candidate + job)

## Co zostało zrobione

### Backend
- **`backend/app/api/ws.py`** — `ConnectionManager` rozszerzony o in-memory mapy:
  - `_viewers: Dict[ResourceKey, Dict[int, Set[WebSocket]]]`
  - `_editing: Dict[ResourceKey, Dict[int, Set[str]]]`
  - `_ws_subs: Dict[int, Dict[WebSocket, Set[ResourceKey]]]` (reverse index dla O(k) cleanupu)
  - `_user_info: Dict[int, ViewerInfo]` (cache imię/email/rola)
  - Nowe metody: `subscribe`, `unsubscribe`, `set_editing`, `get_viewers`, `_cleanup_ws`, `_broadcast_update`
  - `disconnect()` zmieniony na async + woła `_cleanup_ws` przed usunięciem z `_connections`
  - Pętla `ws_notifications` parsuje JSON i routuje `presence:*` eventy
- **`backend/app/api/presence.py`** — nowy plik. Endpoint `GET /api/presence/{candidate|job}/{id}/viewers` (HTTP fallback, `CurrentUser` dependency, `Literal["candidate","job"]` walidacja)
- **`backend/app/main.py`** — zarejestrowany `presence_api.router`

### Frontend
- **`frontend/src/lib/wsBus.ts`** — nowy singleton: `sender` slot + `activePresenceKeys` set + stałe eventowe (`WS_OPEN_EVENT`, `PRESENCE_EVENT`). Pozwala `usePresence` dzielić WebSocket z `useNotifications` bez React Context.
- **`frontend/src/hooks/useNotifications.ts`** — patch:
  - `onopen`: `setWsSender`, dispatch `nexus:ws-open`, replay wszystkich kluczy z `activePresenceKeys` jako `presence:subscribe`
  - `onmessage`: dispatch `nexus:presence` dla każdego frame'u `type.startsWith("presence:")`
  - `onclose`: `clearWsSender()`
- **`frontend/src/hooks/usePresence.ts`** — nowy hook `usePresence(resourceType, resourceId)`:
  - TanStack Query seed z HTTP GET
  - WS subscribe na mount, unsubscribe na unmount/resource change
  - `setEditing(field, active)` z throttle 400ms (leading) + natychmiastowe `active:false`
  - Cleanup editing na `window blur`, `visibilitychange hidden`, unmount
  - Re-subscribe na `nexus:ws-open` (reconnect)
- **`frontend/src/components/v2/presence/ActiveViewers.tsx`** — nowy komponent:
  - Stackowane awatary (max 3 widoczne + `+N` pill z tooltipem overflow)
  - Deterministyczny kolor awataru z hash(email)
  - Tooltip: pełne imię + rola + edytowane pola
  - Ring `#F59E0B` wokół awataru gdy user edytuje jakieś pole
  - Filtr self z listy (po `auth.user.id`)
  - Zwraca `null` gdy 0 innych viewerów (brak ghost UI)
  - Opcjonalny prop `viewers` — żeby parent mógł przekazać istniejącą listę zamiast mountować drugi hook
- **`frontend/src/components/v2/pages/CandidateDetailV2.tsx`**:
  - `const { viewers: presenceViewers, setEditing: setPresenceEditing } = usePresence("candidate", Number(id))` w body
  - `<ActiveViewers resourceType="candidate" resourceId={...} viewers={presenceViewers} />` w hero (obok close button)
  - `NotatkiTab` dostaje `viewers`, `currentUserId`, `setEditing` jako props
  - Textarea notatek: `onFocus={() => setEditing?.("notes", true)}`, `onBlur={() => setEditing?.("notes", false)}`
  - Chip „X edytuje notatki" z animated orange dot pod Textarea
- **`frontend/src/app/jobs/[id]/page.tsx`** — `<ActiveViewers resourceType="job" resourceId={...} />` w headerze obok przycisków akcji

### Testy
- **`backend/tests/test_presence_manager.py`** — 9 unit testów pokrywających:
  - `subscribe_single_user` — struktura payload-u
  - `multiple_tabs_one_viewer` — dedup po `user_id`
  - `unsubscribe_last_tab_drops_viewer` — cleanup gdy ostatnia zakładka się zamyka
  - `unsubscribe_not_last_tab_preserves_viewer` — viewer nie znika przy >1 zakładce
  - `set_editing_toggles_field` — broadcast przy zmianie editing
  - `set_editing_ignores_non_viewer` — guard dla użytkownika nieobecnego
  - `disconnect_cleans_up_presence` — reverse index sprząta wszystkie zasoby
  - `disconnect_with_multiple_tabs_keeps_viewer` — brak broadcast gdy viewer_list bez zmian
  - `get_viewers_snapshot_shape` — walidacja struktury HTTP response
- **`backend/tests/test_presence_api.py`** — 3 integration testy HTTP endpointu (empty initially, requires auth, rejects unknown resource_type — Pydantic Literal → 422)
- **Wynik:** `12 passed, 23 warnings in 4.24s`

### Weryfikacja end-to-end (lokalnie)
Dwa jednoczesne WebSockety z różnymi tokenami JWT (Claude Admin + Anna Test @ recruiter), obaj subskrybują `candidate:1`:
- Oba dostały `presence:update` z obiema osobami w viewerach
- Anna wysłała `presence:editing notes true` → oba WS dostały update z `Anna.editing=["notes"]`
- HTTP GET `/api/presence/candidate/1/viewers` zwrócił ten sam snapshot co WS broadcast

### Weryfikacja na prodzie (`nexus.dynaminds.pl`, po Coolify deploy)
Po pushu commita `f0b716f` Coolify zbudował obie usługi; backend endpoint odpowiedział 403 (wymaga auth) ~31s po pushu. UI smoke test w Chrome:
- Claude Admin zalogowany, otwarty `/candidates/1` → `GET /api/presence/candidate/1/viewers` → 200 ✓
- Seed test-user (POST `/api/admin/users`) → `Anna Test (presence)` id=13 recruiter
- Drugi WS jako Anna → `presence:subscribe` `candidate:1` + `presence:editing notes:true`
- **Hero kandydata:** awatar "A(" fioletowy z pomarańczową obwódką (ring) = edytuje pole
- **Zakładka Notatki:** chip `● Anna Test (presence) edytuje notatki` (animowany orange dot, tekst F59E0B)
- Tooltip na awatarze działa (pełne imię + rola + edytowane pola)

Note: test-user `presence-test@example.com` (id=13) pozostaje na prodzie — brak publicznego endpointu do DELETE usera. Do ręcznego czyszczenia przez bezpośredni SQL na Postgres w Coolify (`UPDATE users SET is_active=false WHERE id=13;` albo DROP), gdy Artur uzna za stosowne.

## Znane ograniczenia

- **1 instancja backendu w prodzie.** Presence trzymane w RAM; restart wyczyści stan. Skalowanie horyzontalne będzie wymagać podmiany `ConnectionManager` na backend za protokołem `PresenceBackend` (`InMemoryBackend` ↔ `RedisBackend`). Struktury `Dict`/`Set` już się bezpośrednio mapują na Redis `HSET`/`SMEMBERS`.
- **Soft editing indicator tylko na polu notatek kandydata** (MVP). Rozszerzenie na inne pola (status, checklist, opis job) trywialne — wystarczy `onFocus/onBlur={() => setEditing("fieldId", bool)}` i chip w UI.
- **Full snapshot broadcast zamiast delta.** Przy <10 viewerach per resource przepustowość pomijalna, eliminuje reordering bugs po reconnect. Zamieniamy na delta dopiero jeśli widzimy realny narzut.
- **Last-write-wins na `POST /api/notes/` bez zmian.** Soft indicator ostrzega ("X edytuje notatki"), nie blokuje — druga osoba nadal może zapisać swoją notatkę. Hard-lock nie był w scope'ie.
- **WS integration test pominięty** — starlette sync TestClient + asyncpg konflikt event-loopów. Pokrycie przez unit testy ConnectionManager + end-to-end smoke przez 2 JS-level WSy.

## Protokół eventów (dla dokumentacji)

### Client → Server (JSON ramki nad istniejącym `/ws/notifications`)

```json
{"type":"presence:subscribe","resource_type":"candidate","resource_id":42}
{"type":"presence:unsubscribe","resource_type":"candidate","resource_id":42}
{"type":"presence:editing","resource_type":"candidate","resource_id":42,"field":"notes","active":true}
```

### Server → Client (broadcast do wszystkich WS subskrybowanych do `key`)

```json
{
  "type": "presence:update",
  "resource_type": "candidate",
  "resource_id": 42,
  "viewers": [
    {
      "user_id": 7,
      "name": "Jan Kowalski",
      "email": "jan@x",
      "role": "recruiter",
      "editing": ["notes"],
      "since": "2026-04-24T10:12:31Z"
    }
  ]
}
```

### HTTP fallback

```
GET /api/presence/{candidate|job}/{id}/viewers
Authorization: Bearer <jwt>
→ 200 { "viewers": [...] }   # ta sama struktura co w presence:update
```

## Kluczowe pliki

Backend:
- [ws.py](../backend/app/api/ws.py) — serce presence state
- [presence.py](../backend/app/api/presence.py) — HTTP fallback
- [test_presence_manager.py](../backend/tests/test_presence_manager.py)
- [test_presence_api.py](../backend/tests/test_presence_api.py)

Frontend:
- [wsBus.ts](../frontend/src/lib/wsBus.ts)
- [useNotifications.ts](../frontend/src/hooks/useNotifications.ts)
- [usePresence.ts](../frontend/src/hooks/usePresence.ts)
- [ActiveViewers.tsx](../frontend/src/components/v2/presence/ActiveViewers.tsx)
- [CandidateDetailV2.tsx](../frontend/src/components/v2/pages/CandidateDetailV2.tsx)
- [jobs/[id]/page.tsx](../frontend/src/app/jobs/[id]/page.tsx)

## Dalsze usprawnienia (poza scope MVP, do rozważenia)

- [ ] Edit indicator na innych polach (status kandydata, checklist profilu Championa, opis job).
- [ ] Presence na liście kandydatów — pokazać dot/avatar dla kandydatów, którzy są aktualnie oglądani przez kogoś. Wymagałoby dodatkowego subskrybowania listy "aktywnych zasobów" — widocznie droższe, ale DX-owo cenne.
- [ ] Redis pub/sub backend — kiedy Nexus dostanie drugą replikę backendu.
- [ ] Czas aktywności ("od 3 minut") wyliczany z pola `since` w tooltipie.
- [ ] Presence dla rozmów (calls) i screeningów w przyszłości — ta sama infrastruktura, nowe `resource_type` i 1 linijka w `_ALLOWED_RESOURCE_TYPES`.
