# Odrzucenie jednym kliknięciem w panelu osoby (23.11.2026)
<!-- indeks: wiersz „Odrzuć:”, `my-quick-reject-reasons`, `quick_reject_reasons.py`, `lib/quick-reject.ts`, `deferReject`, `QuickRejectOutcome`, `initialReasonKey`, 10 s na „Cofnij”, „otwarta: …”, tylko Nowi/Screening, „Za droga…” otwiera okno -->

Decyzja Artura 23.11.2026 — rekomendacja 5 z analizy dnia rekrutera A–Z
(https://claude.ai/artifact/Bf7wiygZoxpTPq9G8oHgiL, „Odrzucenie jednym
kliknięciem”; Artur: „wszystkie naraz”). Pomiar na kopii produkcji: rekruter
odrzuca średnio 19 osób dziennie, 71% prosto z „Nowych”, mediana 35 s przed
odrzuceniem. „Odrzuć z powodem” to okno z 22 powodami i trzy kliknięcia,
a trzy najczęstsze powody danej osoby z 30 dni to średnio 57% jej odrzuceń.

- **Gdzie.** Pod rzędem akcji panelu osoby („Inny etap…”, „Odrzuć z powodem”,
  „Zrezygnował”, „⋯”) wiersz „Odrzuć:” z trzema powodami
  (`PipelineCandidateDock`, prop `quickReject`, `data-testid="dock-quick-reject"`).
  Tylko gdy osoba stoi w „Nowych” albo „Screeningu” (`quickRejectAllowed`),
  panel może odrzucać (`canReject`, bez `rejectBlockedReason`, nie tylko do
  odczytu) i serwer oddał powody. Od „Zweryfikowanego” odrzucenie zostaje
  w oknie: tam jest mail do kandydata, powody klienta, umowa i spotkania
  u klienta. Formularz screeningu w widoku „Rozwiń” skrótu nie ma.
- **Które powody.** `GET /api/pipeline/my-quick-reject-reasons`
  (`services/quick_reject_reasons.py`): wiersze `candidate_stages`
  z `stage = rejected`, `moved_by` = zalogowana osoba, od północy kalendarza
  firmy 30 dni temu (dziś wliczone), bez `ended_by` klienta i kandydata.
  Nazwa wiersza szablonu → klucz słownika (`close_reasons`,
  `QUICK_KEY_BY_TEMPLATE_NAME`); nigdy powody klienta i kandydata ani te
  z obowiązkowym opisem („Inne”, „Już po rozmowie u tego HM”). Mniej niż trzy
  → dopełnienie najczęstszymi w zespole (`source: "team"`, dymek mówi
  „Częsty powód w zespole”). Front filtruje to samo drugi raz
  (`quickRejectChips`) i bierze etykiety okna („Nie spełnia wymagań
  technicznych” = „Brak kluczowej umiejętności”, „Brak doświadczenia” =
  „Za mało doświadczenia”, „Za wysokie oczekiwania finansowe” = „Za droga”).
- **Dostęp.** Trasa ma bramkę sekcji Pipeline i `RecruiterPlus` — jak
  `POST /api/pipeline/move`. Automatyzacje, praktykant i stary `user`
  dostają 403 na obu (`tests/test_quick_reject_reasons.py`), wzorzec
  `tests/data/authz_golden/pipeline.json`.
- **Klik = „Potwierdź” w oknie przy „Odrzucamy my”.** Ten sam `sendMove`
  w `usePipelineMove` (`deferReject`): wiersz szablonu z powodu 1:1
  (`closeTemplateReason`; szablon bez wiersza → „Inne” z nazwą powodu
  w opisie), `ended_by = recruiter`, `send_rejection_email = false` (w tych
  kolumnach mail i tak nie wychodzi), wersja procesu. Domyślne odpowiedzi
  okna: osoba od systemu dostaje powód dla systemu z „Skąd to wiesz?” =
  profil w „Nowych” i rozmowa w „Screeningu” (`quickRejectLearnedFrom`; okno
  tego nie podpowiada, skrót musi), „na cały klient” przy powodach klienta,
  „Nie szuka pracy” na 3 miesiące, a po zapisie spotkania pary do odwołania
  jak zaznaczone w oknie (`RejectionMeetingsField`).
- **„Za droga” i „Lokalizacja lub tryb pracy” otwierają okno** z zaznaczonym
  powodem (`QUICK_REJECT_OPENS_WINDOW`, prop `initialReasonKey` okna, chip
  z wielokropkiem). Okno pyta wtedy o nową stawkę
  (`nowa-stawka-przy-odrzuceniu-za-drogo.md` — po to ją wprowadzono, 51 ze
  118 odrzuceń miało kwotę w opisie) albo „Co nie pasuje?” z kartą dojazdu
  (od 27.11.2026, `karta-dojazdu-przy-odrzuceniu-za-lokalizacje.md`).
- **Cofnij jak strzałka „→” (D7, `kanban-bez-bramek.md`).** Karta idzie na
  „Odrzucony” od razu, a żądanie po 10 s (`DEFERRED_MOVE_MS`), od razu przy
  zamknięciu Tablicy i przy otwarciu tej osoby w panelu („Pokaż”).
  „Cofnij” przed wysłaniem nie wysyła niczego, więc nie zostaje mail,
  dzwonek ani wpis w historii, a panel wraca do tej osoby. Po wysłaniu
  ruch cofa się tylko ręcznie. Odmowa serwera: „Nie odrzucono: <osoba> —
  <powód>” i prawda serwera na Tablicy.
- **Panel przechodzi dalej od razu**, nie po odpowiedzi serwera (inaczej niż
  „Potwierdź”, `nastepna-osoba-po-odrzuceniu.md`) — ruch czeka 10 s.
  Komunikat na dole: „Odrzucono: <osoba> · <powód> · otwarta: <następna>”
  z „Cofnij” (`quickRejectMessage`); po ostatniej osobie kolejki „to była
  ostatnia osoba w kolejce „Nowi”” i panel się zamyka. Pasek nad następną
  osobą („Odrzucono: X · powód · Pokaż”) zostaje jak po oknie.
- **Nowość i Poligon:** wpis `odrzuc-jednym-kliknieciem` i lekcja
  `lekcja-odrzuc-jednym-kliknieciem` (ruch na „Odrzucony” z powodem
  „…doświadczenia”). Poligon nie ma historii ćwiczącego, więc
  `lib/poligon/store.ts` oddaje stałe trzy powody.
- Nowy powód w słowniku, który wymaga dodatkowego pola w oknie = wpis
  w `QUICK_REJECT_OPENS_WINDOW`, inaczej skrót odrzuci go bez tego pola.
- Testy: `backend/tests/test_quick_reject_reasons.py`,
  `frontend/src/lib/__tests__/quick-reject.test.ts`,
  `hooks/__tests__/usePipelineMove.quickReject.test.tsx`,
  `components/v2/jobs/__tests__/PipelineCandidateDock.quickReject.test.tsx`.
