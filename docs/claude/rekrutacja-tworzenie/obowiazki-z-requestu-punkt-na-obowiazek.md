# „Obowiązki” z requestu: każdy obowiązek osobnym punktem po polsku (07.11.2026)

Decyzja Artura z 07.11.2026 (wariant B, makiety
https://claude.ai/artifact/RjnKtLZ3gkku12FabEx69g), po zgłoszeniu Delivery Leada:
klient przysyła opis stanowiska z wieloma punktami, a odczyt maila na `/jobs/new`
zostawiał z tego jedno zdanie. Pomiar z 07.11: 51 z 60 świeżych profili miało
„Obowiązki” w jednej linii (200–400 znaków) przy requestach na 600–19 000 znaków,
a czterech DL-i wklejało potem pełną listę ręcznie (789189, 789191, 789170, 789180).

- **Prompt `JOB_REQUEST_INTAKE` v15:** „Obowiązki” to wszystkie obowiązki i zadania
  z requestu, po polsku, własnymi słowami, jeden punkt („- …”) na jeden obowiązek,
  w kolejności z maila; nazwy obszarów jako osobne linie z dwukropkiem, oczekiwane
  rezultaty jako ostatni obszar. Nazwy systemów, technologii, regulacji i skróty
  (KYC, TM, RTS, GraphQL) zostają bez tłumaczenia. Bez listy obowiązków w mailu:
  2–3 zdania jak dotąd. **Nie kopiujemy zdań klienta 1:1** (decyzja Artura) i nie
  streszczamy do ogólników — tego pilnuje treść promptu, nie kod.
- **Kod (`job_request_intake._responsibilities`)** zachowuje linie (stare `_text`
  sklejało je w jeden akapit), ujednolica znaczniki punktów do „- ”, usuwa punkt
  powtórzony w kilku obszarach (Nordea 43187: dwa punkty w trzech obszarach),
  ogólny nagłówek „Obowiązki:” i obszar bez punktów. Limit
  `MAX_RESPONSIBILITIES_CHARS` = 4000 (najdłuższa próbka, 57 linii opisu, dała
  ok. 3 000); nadmiar odpada całymi punktami z uwagą „Obowiązki: pominięte punkty”
  w `advisories` — nigdy po cichu.
- **Front czyta listę przez `lib/champion-responsibilities.ts`:** Brief pokazuje
  „Obowiązki (N)” z nazwami obszarów, a średnik wewnątrz punktu nie tnie. Tekst
  bez punktów (stare profile) tnie się jak dotąd na liniach i średnikach. Pole
  „Obowiązki” na `/jobs/new` i w pełnym edytorze rośnie z liczbą linii (2–14).
- **Wektor rekrutacji** czyta pierwsze 1 000 znaków „Obowiązków”
  (`embedding_service`) — bez zmian; zapisane profile się nie zmieniają.
- Poziomy „Musi mieć / Mile widziane / Krytyczne” z odczytu maila **odłożone**
  do scalenia innych sesji nad wymaganiami (makiety pomiaru:
  https://claude.ai/artifact/VdN3P5Je73gZr8SZXEdwH1).
