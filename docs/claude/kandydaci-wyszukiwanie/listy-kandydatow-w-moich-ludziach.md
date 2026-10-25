# Listy kandydatów w „Moich ludziach” — „Tylko ja” / „Widzi zespół”
<!-- indeks: zakładka „Listy”, „Na listę” na profilu, masowo z listy kandydatów, `talent_pools.team_visible` (0519), cudza prywatna lista = 404 -->

Prośba Head of Recruitment z 23.10.2026, decyzje Artura z 25.10.2026
(makiety: https://claude.ai/artifact/NV5xibBaWfkHA398NquxGr). „Moi ludzie”
buduje się sam z weryfikacji (`moi-ludzie-lista-rekrutera-dzwonek-przy-nowej.md`),
a ludzie chcieli też dokładać osoby ręcznie i trzymać własne listy.

- **Lista to osobista pula talentów** (`talent_pools.is_personal`, 0137), nie
  nowa tabela. Widoczność to `team_visible` (migracja 0519 + lustro
  w `entrypoint.sh`): `false` = „Tylko ja”, `true` = „Widzi zespół”. Domyślne
  `true` w bazie i w `POST /api/talent-pools` zostawia dawne pule osobiste
  z `/talents` widoczne jak przed 0519; panel i okna list zakładają listy
  z `team_visible=false` (decyzja: nowa lista jest „Tylko ja”). Pula firmowa
  jest zawsze widoczna, flaga liczy się tylko przy osobistej.
- **Cudza lista „Tylko ja” nie istnieje dla nikogo poza właścicielem — także
  dla admina.** Jedna reguła: `services/talent_pool_visibility.py`
  (`is_public`, `is_visible_to`, `visible_clause`, `visible_pool_ids`). Każda
  trasa `/api/talent-pools/*` zwraca na nią 404, lista pul jej nie zawiera,
  `for-candidate` jej nie zgłasza, podpowiadacz pul jej nie proponuje, a pole
  `talent_pools` kandydata (lista i profil) nie niesie list prywatnych w ogóle
  — ta odpowiedź nie zna patrzącego, właściciel widzi swoje w „Na listę”.
  Filtr `talent_pool_id` na `/api/candidates` i w eksporcie zawęża się do
  widocznych pul; same niewidoczne = `[-1]`, czyli zero wyników, nigdy cała
  baza. Powód: sama nazwa listy bywa opinią o człowieku.
- **Zmienia tylko właściciel.** `PATCH /api/talent-pools/{id}` (nazwa,
  `team_visible`) — wyłącznie pula osobista (firmowa: 409) i wyłącznie
  właściciel (inny, także admin: 403). Dodawanie i usuwanie osób zostaje jak
  w 0137: właściciel albo admin; zespół listę „Widzi zespół” tylko ogląda.
- **Front:** `lib/api/candidateLists.ts` (klucze pod `["talent-pools"]`, więc
  stare unieważnienia odświeżają też listy); zakładka „Listy” w panelu
  (`components/v2/my-people/CandidateListsViews.tsx`) — moje listy
  z przełącznikiem „Widzi zespół”, „Udostępnione zespołowi” do podglądu,
  z każdej osoby „Dodaj do rekrutacji”; „Na listę” w nagłówku profilu
  (`candidate-profile/AddToListButton.tsx`, tylko z prawem zapisu, licznik
  liczy wyłącznie moje listy); masowe „Na listę albo do puli” na liście
  kandydatów — moje listy na górze i „Utwórz i dodaj”. Pierwsza zakładka
  panelu nazywa się „Z procesów” (wcześniej „Wszyscy”), żeby nie myliła się
  z listami.
- **Poza zakresem świadomie:** przekazanie listy rekruterowi z terminem
  (decyzja 25.10: nie teraz), edycja cudzej listy przez Head of Recruitment.
