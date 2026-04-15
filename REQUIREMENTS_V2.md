# DynaMinds ATS v2 — Wymagania z analizy Traffit + B2B.net procesów

## Proces Body Leasing B2B.net — Role operacyjne

### Role w systemie (nie tylko user roles — role rekrutacyjne):
1. **Recruiter** — 100% LinkedIn, dodaje kandydatów, premia za samodzielnie dodanych
2. **Sourcer** — 100% baza ATS + ogłoszenia, premia za kandydatów z ATS/ogłoszeń
3. **TAC (Talent Acquisition Consultant)** — hybryda ATS + LinkedIn, współpraca z DL
4. **Delivery Lead (DL)** — zarządza procesem, odpowiada za pytania interview, przypisany do Competence Category
5. **Quality Control** — funkcja doradcza, raporty rekomendacyjne

### Workflow rekrutacji Body Leasing:
1. Zapytanie od klienta (request) → przypisanie DL + rekruterów
2. Sourcing (LinkedIn / ATS / ogłoszenia) → dodanie kandydatów
3. Screening (DL) → notatka ze screeningu
4. Interview z klientem → pytania + feedback
5. Oferta → negocjacja stawki
6. Placement → kontrakt aktywny
7. Ongoing → monitoring, antyrezygnacja

### System premiowy (do śledzenia w ATS):
- Recruiter: 100% premia za samodzielnie dodanych kandydatów
- Sourcer: 100% premia za kandydatów z ATS/ogłoszeń
- Podwójne premiowanie: rekruter 100% + sourcer/TAC 100% gdy sourcer zrekrutuje kandydata dodanego przez rekrutera
- Competence Category: 1st Priority → 2nd Priority

## Brakujące funkcje (z analizy Traffit)

### 1. Profil kandydata 360° (KRYTYCZNE)
- Avatar/zdjęcie
- Email klikalne (otwiera mail client)
- Telefon klikalne (click-to-call)
- Tagi (technologie, poziom, dostępność)
- Źródło kandydata (LinkedIn, Pracuj, ogłoszenie, referral, baza)
- AI Summary — automatyczne podsumowanie CV
- Pliki (CV, portfolio, certyfikaty) z datami
- Historia rekrutacji (w jakich procesach brał udział)
- Timeline aktywności (chronologiczny feed: notatki, zmiany etapów, maile, telefony)

### 2. Otwarte karty (tabs) — jak w Traffit
- Możliwość otwarcia wielu kandydatów/rekrutacji jednocześnie
- Lista otwartych kart z lewej strony
- Szybkie przełączanie

### 3. Aktywności użytkowników (TRACKING)
- Ile kandydatów dodał użytkownik (per dzień/tydzień/miesiąc)
- Ile przesunął na jaki stage
- Ile telefonów wykonał
- Ile screeningów zrobił
- Ile interview zorganizował
- Ile placements zamknął
- Dashboard performance per rekruter/sourcer/DL
- Ranking top performers

### 4. InfraReporter KPIs (do zintegrowania)
Dane z API: https://infrareporter.onrender.com/api/kpi/board/monthly
- Placements per miesiąc (z rozbiciem na klientów)
- Revenue, consultant costs, margin, profit
- Active consultants, departures
- Avg margin per hour, hit ratio
- Placement clients breakdown (Nordea, BNP, Pekao, etc.)
- Trend charts (miesiąc do miesiąca)

### 5. Zaawansowane wyszukiwanie
- Quick search (globalne)
- Filtry: technologie, doświadczenie, lokalizacja, dostępność, stawka
- Filtry po etapie rekrutacji
- Filtry po źródle
- Filtry po rekruterze/DL
- Wyszukiwanie w CV (full-text)
- Semantic search (AI — Voyage embeddings)

### 6. CRM rozszerzony
- Traffit ma 145 klientów z kontaktami
- Potrzebne: kontakty per klient (wiele osób)
- Historia współpracy (ile rekrutacji, ile placements, revenue)
- Status klienta (aktywny/nieaktywny/prospect)
- Notatki per klient

### 7. Raportowanie
- Wyniki rekruterów (ile CV, ile screeningów, ile placements)
- Pipeline per rekrutacja (ile kandydatów na jakim etapie)
- Source effectiveness (skąd przychodzą najlepsi)
- Time-to-hire per pozycja
- Client revenue breakdown
- InfraReporter data overlay
