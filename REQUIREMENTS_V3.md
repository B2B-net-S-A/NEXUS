# DynaMinds ATS v3 — Candidate Intelligence & Client Knowledge

## 1. Client Knowledge Base

Per-client knowledge store:
- selling_points: dlaczego warto pracować (benefity, stack, kultura, zespół)
- interview_questions: pytania per rola/proces (historyczne, kumulatywne)
- historical_placements: kto tam pracuje, jak długo, feedback
- tech_stack: technologie używane u klienta
- culture_notes: kultura pracy, dress code, remote policy
- contacts: osoby kontaktowe (hiring managers, HR)

Model: ClientKnowledge (client_id FK, category, content TEXT, added_by FK, source)
API: CRUD per client

## 2. Screening Notes (Structured)

Osobny typ notatki ze screeningu — nie free-text, a ustrukturyzowane pola:
- motivation_primary: enum (money, growth, project, team, work_mode, stability, technology, location)
- motivation_secondary: enum
- salary_expectation: int + currency
- salary_negotiable: bool
- availability: date
- notice_period: str
- verified_skills: JSONB [{skill, level: confirmed/basic/none, notes}]
- red_flags: text
- personality_notes: text
- readiness_to_change: 1-5
- counteroffer_risk: enum (low/medium/high)
- closing_strategy: text
- overall_impression: 1-5

Model: ScreeningNote (candidate_id FK, job_id FK, author_id FK, all above fields, created_at)
API: CRUD, GET /candidates/{id}/screenings — all screenings for candidate

## 3. AI Candidate Profile (Aggregated)

Auto-generated from all screening notes for a candidate:
- motivation_trend: jak motywacja zmieniała się w czasie
- salary_trend: jak stawki rosły
- verified_skills_aggregate: confirmed skills z wszystkich screeningów
- personality_summary: AI summary osobowości
- best_match_profile: jaki typ projektu/klienta pasuje najlepiej
- warnings: red flags kumulatywne

API: GET /candidates/{id}/ai-profile — auto-generated, cached
Regenerated after each new screening note

## 4. AI Prep Kit (for Preparation Calls)

When DL/recruiter clicks "Przygotuj Prep Kit" on a candidate+job:
AI generates from:
- Job description
- Client knowledge base (selling points, questions, culture)
- Candidate profile (CV, screenings, skills, motivation)
- Historical interview Q&A for this client

Output (structured JSON + rendered view):
- client_overview: opis klienta, stack, kultura
- likely_questions: 5-10 pytań (z historii + AI predicted)
- candidate_strengths: co podkreślić
- candidate_gaps: na co uważać
- selling_points: czym przekonać kandydata
- strategy: rekomendowana strategia prep callu

API: POST /api/prep-kit/generate (job_id, candidate_id)
Frontend: modal/page z prep kitem, print-friendly

## 5. Post-Prep Call Form

After preparation call, recruiter fills structured form:
- All ScreeningNote fields (motivation, salary, skills verified, etc.)
- prep_call_notes: free text
- candidate_convinced: bool
- risk_assessment: enum
- next_steps: text

Saved as ScreeningNote with type='prep_call'
Auto-updates AI Candidate Profile

## 6. CRM Sales Pipeline

Model: SalesOpportunity
- client_id FK, contact_person, title, description
- stage: enum (lead, qualification, proposal, negotiation, won, lost)
- value: decimal
- currency: str
- probability: int (0-100)
- expected_close_date
- assigned_to FK (BDM/Sales)
- lost_reason (if lost)
- notes
- converted_job_id FK (when won → creates Job)

API: CRUD + pipeline view + stats
Frontend: Kanban board for sales pipeline (Lead → Won)
When opportunity = won → auto-creates Job with client info pre-filled

## 7. Contacts (per Company)

Model: Contact
- client_id FK
- name, email, phone, position, department
- is_decision_maker: bool
- notes
- last_contacted_at

API: CRUD, nested under clients
Frontend: Contacts tab on client detail page
