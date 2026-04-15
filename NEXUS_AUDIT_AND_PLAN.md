# DynaMinds Nexus — Audit & Strategic Plan
**Data: 2026-03-19 | Autor: Jarvis**

---

## 🔍 AUDIT — Uczciwa ocena każdego modułu

### ✅ CO DZIAŁA DOBRZE (produkcyjne jakościowo)
| Moduł | Ocena | Komentarz |
|-------|-------|-----------|
| Dashboard | ⭐⭐⭐⭐ | KPI cards, lejek rekrutacji, leaderboard, aktywność — solidne |
| Kandydaci — lista | ⭐⭐⭐⭐ | Master-detail, filtrowanie, search, tagi, source icons |
| Kandydat — profil 360° | ⭐⭐⭐⭐ | AI Summary, Screening stats, oczekiwania, dostępność, tagi |
| Oferty pracy — lista | ⭐⭐⭐⭐ | Karty z tagami (Body Leasing/Sprzedaż/Przetarg), priorytety, widełki |
| Kanban pipeline | ⭐⭐⭐ | Drag & drop działa, ale ZA MAŁO STAGE'ÓW — generyczny, nie B2B.net |
| Pipeline sprzedażowy | ⭐⭐⭐⭐ | Lead→Kwalifikacja→Oferta→Negocjacje — ładne karty z kwotami |
| Klienci | ⭐⭐⭐⭐ | Tabela, branża, kontakt, status, NDA — czytelne |
| Kontakty | ⭐⭐⭐⭐ | DM tracking, grupowanie wg firmy |
| Kontrakty | ⭐⭐⭐ | Tabela z marżami — ALE: pokazuje ID zamiast nazw (Kandydat ID: 3 zamiast "Piotr Kowalski") |
| Kalendarz | ⭐⭐⭐⭐ | Tygodniowy widok, typy wydarzeń, color coding |
| Raporty | ⭐⭐⭐⭐ | 5 tabów, lejek, źródła, Liga Mistrzów — ładne wizualnie |
| Analityka | ⭐⭐⭐⭐⭐ | Źródła, czas w pipeline, aktywność zespołu, konwersje — najlepszy moduł |
| Pule talentów | ⭐⭐⭐ | 3 pule z kandydatami — działa, ale brak operacji (dodaj/usuń kandydata z puli) |
| Ustawienia | ⭐⭐⭐ | Fireflies integracja + szablony email + pomoc |

### ⚠️ PROBLEMY KRYTYCZNE
1. **Pipeline za prosty** — 7 generycznych etapów. B2B.net ma specyficzny flow:
   - Sourcing → Prep Call → Screening → Wysłanie do klienta → Interview u klienta → Akceptacja → Negocjacje → Onboarding → Kontrakt aktywny
2. **Brak panelu managera** — Olaf/Dominik nie mają widoku "bird's eye": ile ludzi na jakim etapie, gdzie bottleneck, kto potrzebuje pomocy
3. **Oferty pokazują "0 kandydatów"** — seed nie powiązał pipeline z większością jobów
4. **Kontrakty: ID zamiast nazw** — "Kandydat ID: 3" jest nieczytelne
5. **Admin panel pusty** — czarny ekran, nic się nie renderuje
6. **Prep Kit / CV Generator / Screening** — istnieją w kodzie, ale z profilu kandydata nie są widoczne w intuicyjny sposób (przyciski są, ale efekt trudny do oceny bez danych)

### 🟡 BRAKUJĄCE ELEMENTY (kluczowe dla produkcji)
1. **Manager Dashboard** — widok bottleneck/workload/alertów
2. **Customizable pipeline stages** — B2B.net flow, nie generyczny ATS
3. **Realistyczne dane seedowe** — żeby ocenić UI z prawdziwym obciążeniem
4. **Bulk actions** — zaznacz wielu kandydatów → przenieś, taguj, wyślij email
5. **Activity timeline na profilu kandydata** — kto kiedy co zrobił
6. **Notyfikacje inteligentne** — "3 kandydatów czeka >5 dni na screening" itp.

---

## 🎯 PLAN STRATEGICZNY — 4 FAZY

### Definicja "DONE"
Nexus jest gotowy do wewnętrznego pilota gdy:
- [ ] Zespół rekrutacji (Olaf + 3 DL) może pracować codziennie zamiast Traffit
- [ ] Manager widzi bottlenecki i workload w real-time
- [ ] Pipeline odzwierciedla rzeczywisty proces B2B.net
- [ ] Dane z Traffit (min. aktywni kandydaci) są zmigrowane
- [ ] System działa na serwerze, nie na laptopie

---

### FAZA 1: FUNDAMENT (Tydzień 1) — "Useable Core"
**Cel:** System działa z prawdziwym pipeline B2B.net, realistyczne dane, krytyczne bugi naprawione.

| # | Task | Priorytet | Effort |
|---|------|-----------|--------|
| 1.1 | Pipeline stages → B2B.net flow (10 etapów customizowanych) | 🔴 KRYTYCZNY | 4h |
| 1.2 | Kontrakty: nazwy zamiast ID | 🔴 KRYTYCZNY | 1h |
| 1.3 | Admin panel — naprawić rendering | 🔴 KRYTYCZNY | 2h |
| 1.4 | Seed v6: realistyczne dane (100+ kandydatów, 10 jobów, pełny pipeline) | 🔴 KRYTYCZNY | 4h |
| 1.5 | Oferty pracy: fix "0 kandydatów" counter | 🟡 WAŻNY | 1h |

**Deliverable:** Artur + Olaf mogą otworzyć system i zobaczyć realistyczny pipeline

---

### FAZA 2: MANAGER VIEW (Tydzień 2) — "Kontrola"
**Cel:** Manager rekrutacji widzi workload, bottlenecki, i wie gdzie pomóc.

| # | Task | Priorytet | Effort |
|---|------|-----------|--------|
| 2.1 | Manager Dashboard: bird's eye wszystkich jobów + stage'ów | 🔴 KRYTYCZNY | 6h |
| 2.2 | Bottleneck alerts (dużo kandydatów na prep call → "Pomóż!") | 🔴 KRYTYCZNY | 3h |
| 2.3 | Workload per rekruter (ile kto ma otwartych procesów) | 🟡 WAŻNY | 3h |
| 2.4 | Aging alerts (kandydat czeka >X dni na danym stage) | 🟡 WAŻNY | 2h |
| 2.5 | Bulk actions (zaznacz → przenieś, taguj) | 🟡 WAŻNY | 4h |

**Deliverable:** Olaf/Dominik mają pełną kontrolę nad pipeline

---

### FAZA 3: MIGRACJA & DEPLOY (Tydzień 3) — "Produkcja"
**Cel:** Prawdziwe dane, prawdziwy serwer, zespół testuje.

| # | Task | Priorytet | Effort |
|---|------|-----------|--------|
| 3.1 | Deploy na serwer (Render/VPS) z HTTPS | 🔴 KRYTYCZNY | 4h |
| 3.2 | Migracja aktywnych kandydatów z Traffit (CSV/scraping) | 🔴 KRYTYCZNY | 8h |
| 3.3 | Auth & permissions (role: admin/manager/recruiter/viewer) | 🟡 WAŻNY | 6h |
| 3.4 | Teams/Outlook calendar sync | 🟡 WAŻNY | 4h |
| 3.5 | CloudTalk integration (po callu 20.03) | 🟢 NICE-TO-HAVE | 4h |

**Deliverable:** Zespół pracuje na Nexus z prawdziwymi danymi

---

### FAZA 4: AI & SCALE (Tydzień 4+) — "Przewaga"
**Cel:** AI features, automatyzacja, inteligentne rekomendacje.

| # | Task | Priorytet | Effort |
|---|------|-----------|--------|
| 4.1 | AI Matching produkcyjny (Voyage embeddingi na realnych CV) | 🟡 WAŻNY | 4h |
| 4.2 | Auto-screening z Fireflies (transkrypcja → structured notes) | 🟡 WAŻNY | 6h |
| 4.3 | Pracuj.pl auto-import do pipeline (nie tylko do bazy) | 🟡 WAŻNY | 3h |
| 4.4 | Email integration (wysyłanie z systemu) | 🟢 NICE-TO-HAVE | 6h |
| 4.5 | Career page (oferty publiczne) | 🟢 NICE-TO-HAVE | 4h |

---

## 📊 TIMELINE

```
Tydzień 1 (19-26.03): FAZA 1 — Fundament
Tydzień 2 (26.03-2.04): FAZA 2 — Manager View  
Tydzień 3 (2-9.04): FAZA 3 — Migracja & Deploy
Tydzień 4+ (9.04+): FAZA 4 — AI & Scale

🏁 FINISH LINE: 9 kwietnia — zespół używa Nexus zamiast Traffit
```

## 🚀 NASTĘPNY KROK

Faza 1, Task 1.1: Przebudować pipeline stages pod B2B.net.
Zacząć teraz?
