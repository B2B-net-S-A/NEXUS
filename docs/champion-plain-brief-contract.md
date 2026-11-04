# Kontrakt API: „Champion po ludzku”, ściąga do rozmowy, biblioteka ról, słowniczek

Makiety: https://claude.ai/artifact/WEVyKuavTdd8JVggXQ9mD3 (v7). Wszystkie teksty po polsku.
Wszystkie trasy pod `/api`. Wiedza ogólna (słowniczek, role, opis klienta) jest wspólna i zapisana raz;
teksty rekrutacji liczą się z profilu Championa.

## `GET /api/jobs/{job_id}/plain-brief`
Odczyt dla każdej roli wewnętrznej z dostępem do rekrutacji. NIC nie zapisuje i nie woła AI.

```jsonc
{
  "job_id": 4812,
  "status": "none" | "ready" | "failed",   // none = jeszcze nie wygenerowano
  "stale": false,            // true = profil zmienił się od generacji (albo status none)
  "is_open": true,           // rekrutacja otwarta: front sam woła refresh przy stale
  "can_refresh": true,       // false w trybie „podgląd jako”
  "can_change_role": false,  // admin + head_of_recruitment
  "generated_at": "2026-09-29T10:12:00Z" | null,
  "message": null | "Nie udało się przygotować wyjaśnienia — spróbuj „Odśwież”.",
  "one_liner": "Szukamy programisty Javy, który…" | null,
  "example": "Gdy ktoś płaci kartą w sklepie…" | null,     // „Przykład z codzienności”
  "day_to_day": ["…", "…", "…"],
  "pitch": "Dzwonię w sprawie projektu w …" | null,       // tekst na start rozmowy
  "candidate_qa": [
    { "key": "client" | "rate" | "work" | "mode" | "start" | "process" | "team",
      "question": "Co to za klient?",
      "answer": "…" | null,           // null = „brak w profilu”
      "source": "karta klienta" | "sekcja 1" | "sekcja 5" | null }
  ],
  "screening_plain": [
    { "question_id": "q1",
      "question": "„Opisz ostatni system w Spring Boocie…”",  // treść pytania z profilu
      "why": "Sprawdzasz, czy…",
      "good": "Mówi, z jakich części…",
      "reject": "Pracował tylko przy…" | null,               // null gdy profil nie ma deal breakera
      "original": { "ideal_answer": "…", "deal_breaker": "…" } }
  ],
  "glossary": [
    { "term_key": "kafka",
      "display_name": "Kafka",
      "level": "must" | "nice" | "experience",
      "level_label": "wymagane" | "mile widziane" | "doświadczenie · min. 2 lata",
      "status": "ready" | "researching" | "failed" | "missing",  // missing = brak w słowniczku
      "summary": "Taśmociąg, po którym…" | null,
      "does": "…" | null,
      "cv_hints": ["Apache Kafka", "Confluent"],
      "confused_with": "RabbitMQ robi podobną rzecz…" | null,
      "in_this_project": "Po niej płyną transakcje…" | null,
      "sources": [{ "url": "https://…", "title": "…" }],
      "origin": "seed" | "ai" | "manual" | null }
  ],
  "role": null | {
    "id": 7, "slug": "java-backend-bankowosc", "name": "Java backend w bankowości",
    "summary": "…", "example": "…", "day_to_day": ["…"], "candidate_questions": ["…"],
    "typical_skills": ["Java", "Spring Boot"], "sources": [{ "url": "…", "title": "…" }],
    "origin": "seed" | "ai" | "manual", "status": "ready" | "researching" | "failed",
    "assignment": "auto" | "manual",
    "stats": { "jobs": 38, "clients": 9, "hires": 11,
               "hired_titles": [{ "title": "Java Developer", "count": 6 }] }  // hired_titles puste, gdy hires < 3
  },
  "client": null | {
    "id": 211, "name": "Bank Północny",
    "about": "…" | null,
    "origin": "manual" | "web" | null,
    "sources": [{ "url": "…", "title": "…" }]
  }
}
```
Bez stawek osób zatrudnionych. Stawka rekrutacji pojawia się wyłącznie w `pitch` i odpowiedzi `rate`.

## `POST /api/jobs/{job_id}/plain-brief/refresh`
Generuje teksty rekrutacji. W żądaniu robi też research nowej roli i brakującego opisu klienta (wpływają
na teksty); brakujące hasła słowniczka wraca jako `status: "researching"` i bada w tle. Zwraca to samo co GET.
Limit 10/min na osobę (429). Zwykle 20–60 s (przy nowej roli dłużej), więc front używa długiego timeoutu. Dopóki
któreś hasło ma `researching`, front dociąga GET co 10 s (najwyżej 30 razy).
Bramka: każda rola wewnętrzna z odczytem rekrutacji (także tylko-odczyt Pipeline); w „podglądzie jako” 403.

## `PUT /api/jobs/{job_id}/role-profile`
Body `{ "role_profile_id": 7 | null }`. Admin + Head of Recruitment (403 dla reszty). Zwraca GET.

## Biblioteka ról
- `GET /api/role-profiles?q=` → `{ "items": [ { id, slug, name, summary, origin, status, jobs, updated_at } ] }`
- `GET /api/role-profiles/{id}` → pełna rola jak `role` w GET wyżej (bez `assignment`) + `history`:
  `[{ "created_at", "user_name", "changes": { "field": { "old": …, "new": … } } }]`
- `PUT /api/role-profiles/{id}` body `{ name, summary, example, day_to_day[], candidate_questions[], typical_skills[] }`
  → pełna rola. Admin + Head of Recruitment. Ustawia `origin=manual`.

## Słowniczek (w Słowniku umiejętności)
- `GET /api/skills-admin/plain-terms?q=&scope=all|dictionary|outside` →
  `{ "items": [ { id, term_key, display_name, summary, does, cv_hints[], confused_with, sources[], origin,
  status, in_dictionary, updated_at, updated_by_name } ] }`
- `PUT /api/skills-admin/plain-terms/{id}` body `{ display_name, summary, does, cv_hints[], confused_with }`
  → wiersz. Admin + Head of Recruitment. Ustawia `origin=manual`.
- `GET /api/skills-admin/plain-terms/{id}/history` → jak historia roli.

## Karta klienta
`GET/PUT /api/clients/{id}/playbook` — odpowiedź dostaje `about_for_candidate_origin` (`manual|web|null`)
i `about_for_candidate_sources` (`[{url,title}]`). Zapis bez zmian w uprawnieniach.
