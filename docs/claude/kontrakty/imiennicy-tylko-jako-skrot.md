# Imiennicy: dwie osoby o tych samych danych, w repo tylko skrót

Jedno imię i nazwisko należy do dwóch różnych osób. Rozróżnia je e-mail profilu
kandydata. Repo jest publiczne, więc od 26.11.2026 (decyzja Artura) para stoi
w kodzie wyłącznie jako skrót SHA-256 — nie jako tekst, także w testach,
komunikatach i dokumentach.

- **Gdzie:** `backend/app/services/contractor_identity.py` —
  `NAMESAKE_NAME_DIGESTS`, `is_namesake_pair` i lustro SQL
  w `contractor_identity_sql_expression`. Skrót liczy się z „imię nazwisko” po
  `normalize_contractor_name_part`, rozdzielonych jedną spacją.
- **Co od tego zależy:**
  - liczniki kontraktorów: dwa e-maile to dwie osoby, profil bez e-maila liczy
    się osobno;
  - Generator umów B2B nie pozwala podpiąć umowy jednej z tych osób pod
    kontrakt drugiej;
  - SharePoint pomija dokumenty tych osób w obu kierunkach
    (`contract_folder_docs/matching.py`, dokładnie te dwa słowa w dowolnej
    kolejności).
- **Nowa para:** skrót policz lokalnie (nazwiska nie wpisuj do repo, commita ani
  logów) i dopisz do `NAMESAKE_NAME_DIGESTS`. Pierwsze 16 znaków — dla obu
  kolejności słów — dopisz w środku zbioru
  w `frontend/src/__tests__/fixtures/real-people.ts`.
- **Testy** używają osoby zmyślonej i podmieniają zbiór skrótów
  (`backend/tests/_namesake_pair.py`).
- **Strażnicy:** `tests/test_contractor_identity.py` pilnuje, że skrót stoi też
  na liście strażnika repo i że kod aplikacji nie nazywa tych osób.
