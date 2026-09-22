# Strona kariery dla kandydatów — raport (22.09.2026)

Makiety: https://claude.ai/artifact/2uFHLoYDcmaGuCUD7Ncxnr

## Co powstało
- **Backend:** migracja `0339_career_links` (+ lustro w `entrypoint.sh`, sondy `/api/health/deep`):
  - `candidate_invite_links.kind/slug/visit_count`, `job_id` i `expires_at` NULL-owalne;
  - tabele `job_public_profiles`, `candidate_consents`;
  - klucz AI `job_public_description`.
- **Publiczne API** `/api/public/career`:
  - `GET /r/{slug}`
  - `GET /p/{slug}`
  - `POST /apply`
- **API w NEXUSIE:**
  - `/api/me/career-link` (GET/PUT/DELETE, `slug-available`);
  - `/api/jobs/{id}/public-profile` (GET/PUT, `/draft`, `/approve`, `/visibility`);
  - rozszerzone `/api/invite-links`.
- **Serwisy:** `public_apply`, `job_public_profile`, `public_profile_lint`, `career_slugs`, `career_consent`.
- **Frontend:**
  - strony `app/kariera/*` (rekrutacja, link rekrutera, RODO, OG obrazy, 404), komponenty `components/career/*`;
  - routing po hoście w `middleware.ts`;
  - okno „Udostępnij rekrutację” z dwiema zakładkami (`components/v2/career-share/*`);
  - zgoda w starym `/apply/[token]`;
  - harnessy `/preview/kariera` i `/preview/career-share`.

## Do zrobienia poza kodem
1. **DNS:** rekord `kariera.dynaminds.pl` w Cloudflare.
2. **Coolify, serwis frontend:** domena i build arg `NEXT_PUBLIC_CAREER_HOST=kariera.dynaminds.pl`.
3. **Coolify, backend:** `CAREER_PUBLIC_BASE_URL=https://kariera.dynaminds.pl` oraz `CORS_ORIGINS` + `https://kariera.dynaminds.pl`.
4. **Akceptacja prawna** treści zgody i klauzuli `/kariera/rodo` (placeholdery: e-mail kontaktowy, okres przechowywania).

Do tego czasu strona działa pod `https://nexus.dynaminds.pl/kariera/...` i tam prowadzą generowane linki.

## Znane ograniczenia
- Wejścia (`visit_count`) liczą też crawlera LinkedIna przy generowaniu podglądu.
- Kontrola publikacji skanuje tytuł rekrutacji; klient w tytule blokuje publikację (tytułu nie da się zmienić z opisu publicznego).
- `notFound()` na stronach kariery w trybie dev zwraca 200 (strumieniowanie przez `loading.tsx`); treść i `noindex` są poprawne.
