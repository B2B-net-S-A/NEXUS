"""Pydantic schemas dla CV per rekrutacja.

Mirror `app/schemas/contract.py` (Contract Draft):

* `CVOriginalSnapshotResponse`     — GET /cv/original
* `StageCvUploadResponse`          — POST /cv/original/upload (CV kandydata albo do klienta)
* `CVBrandedResponse`              — GET /cv/branded (mirror ContractDraftResponse)
* `CVBrandedUpdate`                — PATCH /cv/branded (XOR: content_html | template+language)
* `CVBrandedFinalizeResponse`      — POST /cv/branded/finalize
* `CVShareTokenResponse`           — POST /cv/share-token
* `PublicCVView`                   — GET /api/public/cv/{token} (no PII)
"""

from __future__ import annotations

from uuid import UUID

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

BrandedStatusLiteral = Literal["none", "draft", "finalized"]
TemplateLiteral = Literal["standard", "blind"]
LanguageLiteral = Literal["pl", "en"]

# Najdłuższa treść CV, jaką przyjmuje zapis z edytora (PATCH, zatwierdzenie).
# Podgląd importu Worda odmawia dłuższego wyniku — nie dałoby się go zapisać.
CV_CONTENT_HTML_MAX = 500_000


class CVOriginalSnapshotResponse(BaseModel):
    candidate_stage_id: int
    candidate_id: int
    job_id: int
    has_snapshot: bool
    original_cv_filename: Optional[str] = None
    original_cv_language: Optional[str] = None
    original_snapshot_at: Optional[datetime] = None
    original_snapshot_source: Optional[str] = None
    download_url: Optional[str] = None


class CVBrandedSelectGenerated(BaseModel):
    expected_revision: int = Field(ge=0)
    generated_document_id: int = Field(ge=1)
    document_version_id: int | None = Field(default=None, ge=1)
    # „Napisz od nowa” (Edytor CV 3, PR 5): części szkicu poprawione ręcznie
    # zostają w wersji rekrutera (`services/cv_rewrite_merge.py`).
    keep_edits: bool = False


class CVBrandedRestorePrevious(BaseModel):
    expected_revision: int = Field(ge=0)


class CVBrandedDiscard(BaseModel):
    """„Odrzuć to CV i zacznij od nowa” (21.10.2026) — wersja, którą rekruter widział."""

    expected_revision: int = Field(ge=0)


class CVBrandedRewrite(BaseModel):
    """Wynik podmiany szkicu nową generacją — zdanie i „Wróć do poprzedniej” w karcie."""

    # Części zostawione w wersji rekrutera, np. „Logistyka 24”, „Języki”.
    kept: list[str] = Field(default_factory=list)
    # `False` = ręcznych poprawek nie dało się rozpoznać; szkic to cała nowa wersja.
    recognized: bool = True
    # Poprzedni szkic jest w migawce — „Wróć do poprzedniej” zadziała.
    can_restore: bool = False


class CVBrandedSelectDocument(BaseModel):
    expected_revision: int = Field(ge=0)
    document_id: int = Field(ge=1)


class CVBrandedSelectStageCv(BaseModel):
    expected_revision: int = Field(ge=0)
    source_job_id: int = Field(ge=1)


class CVBrandedConsentAttach(BaseModel):
    consent_screenshot_token: str = Field(min_length=1, max_length=4096)


class CVBrandedOrigin(BaseModel):
    """Skąd przyszła treść CV wybranego zamiast generacji (12.10.2026).

    ``selected_at`` to chwila wyboru: karta proponuje „Użyj nowej wersji”
    tylko dla generacji młodszych od niej — data edycji przesuwa się z każdym
    zapisem i chowałaby generację, o którą rekruter sam poprosił.
    """

    kind: Literal[
        "stage_copy", "reassign", "upload", "profile_file", "generated_other_job"
    ]
    label: Optional[str] = None
    job_id: Optional[int] = None
    selected_at: Optional[datetime] = None


class StageCvSourceItem(BaseModel):
    """Gotowe CV tej osoby z innej rekrutacji — jedno na rekrutację."""

    job_id: int
    # Wiersz etapu, na którym leży CV — podgląd idzie zwykłym `GET …/cv/branded`
    # (z jego bramką zakresu rekrutacji).
    stage_id: int
    job_title: Optional[str] = None
    reference_number: Optional[str] = None
    client_name: Optional[str] = None
    status: Literal["draft", "finalized"]
    version: int = 1
    language: Optional[str] = None
    blind: bool = False
    updated_at: Optional[datetime] = None
    updated_by_name: Optional[str] = None
    # Ten sam klient i źródło ma zrzut zgody — pojedzie z kopią.
    consent_carried: bool = False


class StageCvSourcesResponse(BaseModel):
    items: list[StageCvSourceItem]


class CVReviewFinding(BaseModel):
    """Uwaga kontroli AI z tekstem linii CV, której dotyczy."""

    text: str
    status: str


class CVContentReviewIssues(BaseModel):
    status: Literal["verified", "reviewed", "unverified"] | None = None
    # Zatwierdzona wersja, której dotyczy kontrola (biegnie po „Zapisz”).
    version: int | None = None
    findings: list[CVReviewFinding] = []


class CVEditorDismissal(BaseModel):
    """Kto, kiedy i dlaczego oznaczył uwagę jako nieprawdziwą (D5)."""

    id: int
    reason: str
    reason_label: str
    note: str | None = None
    by_name: str | None = None
    at: datetime


class CVEditorDismissed(BaseModel):
    source: Literal["generator", "review"]
    text: str
    status: str | None = None
    dismissal: CVEditorDismissal


class CVEditorIssues(BaseModel):
    """Dane panelu „Do poprawy” w edytorze CV: uwagi generatora i kontroli AI."""

    generated_document_id: int | None = None
    generator_warnings: list[str] = []
    content_review: CVContentReviewIssues = CVContentReviewIssues()
    # Uwagi oznaczone „To nieprawda” (D5) — poza listą, z przywróceniem.
    dismissed: list[CVEditorDismissed] = []


class CVEditorDismissRequest(BaseModel):
    source: Literal["generator", "review"]
    text: str = Field(min_length=1, max_length=1000)
    status: str | None = Field(default=None, max_length=40)
    reason: Literal[
        "in_cv",
        "other_name",
        "wrong_place",
        "not_needed",
        "other",
        "kept_order",
        "kept",
    ]
    note: str | None = Field(default=None, max_length=500)


class CVBrandedResponse(BaseModel):
    presentation_review: dict | None = None
    # Domyślne wyrównanie treści w pliku Word (reguła klienta zamrożona przy
    # generacji, `cv_text_align.py`). Akapit z jawnym `text-align` wygrywa.
    text_align: Literal["justify", "left"] = "justify"
    docx_available: bool = False
    docx_filename: str | None = None
    generated_document_id: int | None = None
    from_generator: bool = False
    # Skąd treść: generator (także kopia z innej rekrutacji), plik Word
    # z profilu kandydata albo stary szablon „CV firmowe”.
    source: Optional[Literal["generator", "document", "legacy"]] = None
    # Kopia wybrana zamiast generacji: CV etapu z innej rekrutacji, plik
    # z profilu albo z dysku, przepięcie. ``None`` = CV z generatora tej pary.
    origin: Optional[CVBrandedOrigin] = None
    # Wymóg zrzutu zgody RODO zamrożony na CV etapu i to, czy CV ma własny
    # obraz. Kopia bez dokumentu generatora nie ma innego miejsca, z którego
    # karta mogłaby to odczytać. ``consent_missing`` liczy wyłącznik blokady.
    consent_required: bool = False
    consent_attached: bool = False
    consent_missing: bool = False
    edit_revision: int = 0
    version: int = 1
    candidate_stage_id: int
    status: BrandedStatusLiteral
    content_html: Optional[str] = None
    template: Optional[str] = None
    language: Optional[str] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[int] = None
    updated_by_name: Optional[str] = None
    finalized_at: Optional[datetime] = None
    finalized_by: Optional[int] = None
    finalized_by_name: Optional[str] = None
    snapshot_filename: Optional[str] = None
    rendered_from_default: bool = False
    # Runda 11 (PIPE-3): etap bez własnego CV (``none``) wskazuje wiersz etapu
    # tej pary, na którym leży CV firmowe (ruch na kolejną kolumnę zakłada nowy
    # wiersz bez CV) — jak ``screening_source_stage_id`` przy arkuszu.
    pair_source_stage_id: Optional[int] = None
    pair_source_status: Optional[BrandedStatusLiteral] = None
    # Tylko w odpowiedzi na podmianę szkicu nową generacją (PR 5).
    rewrite: Optional[CVBrandedRewrite] = None


class StageCvUploadResponse(CVOriginalSnapshotResponse):
    """Wynik wgrania CV w rekrutacji (`…/cv/original/upload`, 15.10.2026).

    Pola oryginału zostają na wierzchu jak dotąd. ``outcome`` mówi, czym
    plik się stał: CV kandydata (``original``), CV do klienta tej rekrutacji
    (``client_cv``) albo tylko plikiem w profilu, bo klient ma już CV tej
    osoby (``client_cv_kept``).
    """

    outcome: Literal["original", "client_cv", "client_cv_kept"] = "original"
    uploaded_filename: Optional[str] = None
    client_cv: Optional[CVBrandedResponse] = None
    # Wiersz etapu z CV do klienta pary — po ruchu karty bywa wcześniejszy.
    client_cv_stage_id: Optional[int] = None
    # Co zastąpiło: nic, nieprzejrzane auto-CV albo CV po potwierdzeniu.
    replaced: Optional[Literal["none", "auto_cv", "confirmed"]] = None
    # „Cofnij” w komunikacie: tylko gdy nie zastąpiliśmy niczyjej pracy.
    undo_available: bool = False
    stored_in_profile: bool = False
    # Dokument profilu z wgranym plikiem — karta potwierdza go jako plik CV.
    uploaded_document_id: Optional[int] = None
    # CV do klienta po nowym CV (29.10.2026, `services/new_cv_company_cv.py`):
    # generuje się samo, pytamy, czeka na potwierdzenia, zablokowane po
    # „CV wysłane” albo klient bierze własny formularz. Puste = cofnięcie
    # wgrania CV do klienta albo plik został CV do klienta.
    company_cv: Optional[
        Literal["regenerating", "ask", "confirm", "locked", "none"]
    ] = None
    company_cv_stage_id: Optional[int] = None
    company_cv_status: Optional[str] = None
    regenerating_document_id: Optional[int] = None


class CVBrandedRegenerateFromOriginal(BaseModel):
    """„Generuj z nowego CV” — rewizja szkicu, który zastąpi gotowa wersja."""

    expected_revision: int = Field(ge=0)


class CVBrandedRegenerateResponse(BaseModel):
    generated_document_id: int
    company_cv_stage_id: int


class CVBrandedUpdate(BaseModel):
    """PATCH body — exactly one of {content_html} or {template+language} must be set.

    * `content_html` → save edited Tiptap HTML.
    * `template` and/or `language` → 410 (the legacy HTML template was
       retired in generator v3; drafts come from the CV generator).
    """

    expected_revision: int = Field(ge=0)
    content_html: Optional[str] = Field(default=None, max_length=CV_CONTENT_HTML_MAX)
    template: Optional[TemplateLiteral] = None
    language: Optional[LanguageLiteral] = None

    @model_validator(mode="after")
    def _exclusive_branches(self) -> "CVBrandedUpdate":
        save_branch = self.content_html is not None
        rerender_branch = self.template is not None or self.language is not None
        if save_branch == rerender_branch:
            # Both set OR neither set — invalid.
            raise ValueError(
                "Provide exactly one of: 'content_html' (save) or 'template'/'language' (re-render)."
            )
        return self


class CVBrandedFinalize(BaseModel):
    expected_revision: int = Field(ge=0)
    content_html: str = Field(min_length=1, max_length=CV_CONTENT_HTML_MAX)


class CVBrandedReview(CVBrandedFinalize):
    request_key: UUID


class CVBrandedNewDraft(BaseModel):
    expected_revision: int = Field(ge=0)


class CVVersionSummary(BaseModel):
    """Zatwierdzona wersja CV etapu na liście historii w edytorze."""

    version: int
    # ``None`` tylko dla CV zatwierdzonego bez zapisanej daty (stare wiersze).
    approved_at: Optional[datetime] = None
    # Imię i nazwisko z konta, nie e-mail; ``None``, gdy konta już nie ma.
    approved_by_name: Optional[str] = None
    language: LanguageLiteral
    docx_available: bool = False
    # Wersja, którą etap pokazuje teraz jako zatwierdzoną.
    is_current: bool = False


class CVVersionsResponse(BaseModel):
    """Od najnowszej. Pusta lista = CV nie było jeszcze zatwierdzone."""

    versions: list[CVVersionSummary]


class CVVersionContent(BaseModel):
    version: int
    content_html: str
    language: LanguageLiteral
    approved_at: Optional[datetime] = None


class CVImportPreview(BaseModel):
    """Plik Word jako HTML edytora — odpowiedź trasy, która nic nie zapisuje."""

    content_html: str
    filename: str


class CVBrandedFinalizeResponse(BaseModel):
    edit_revision: int
    version: int
    document_version_id: int
    candidate_stage_id: int
    status: BrandedStatusLiteral
    snapshot_filename: str
    snapshot_size_bytes: int
    # Wynik niezależnej kontroli AI treści (0326). Zatwierdzenie przechodzi
    # także z uwagami — rekruter ma je zobaczyć PO fakcie, a nie zostać
    # zablokowany przed wysyłką. `None` = kontrola nie biegła.
    content_review_status: Optional[str] = None
    content_review_findings: Optional[int] = None


class CVShareTokenResponse(BaseModel):
    token: str
    expires_at: Optional[datetime] = None
    share_url_suffix: str = Field(
        ..., description="np. '/cv/abc123' — FE skleja z window.location.origin"
    )
    candidate_stage_cv_id: int
    # M4 PR-04 (token v2): nie-sekretny identyfikator do revoke-by-ID.
    # Raw token jest zwracany TYLKO tutaj (raz); potem istnieje wyłącznie hash.
    revoke_key: Optional[str] = None
    max_views: Optional[int] = None


class CVShareTokenListItem(BaseModel):
    """Metadane aktywnego/odwołanego linku — bez sekretu (M4 PR-04, P1.9)."""

    revoke_key: str
    token_preview: str = Field(..., description="maskowany identyfikator do UI")
    is_v2: bool
    created_at: Optional[datetime] = None
    created_by_name: Optional[str] = None
    expires_at: Optional[datetime] = None
    revoked: bool
    revoked_at: Optional[datetime] = None
    revoke_reason: Optional[str] = None
    view_count: int = 0
    max_views: Optional[int] = None
    last_viewed_at: Optional[datetime] = None
    purpose: Optional[str] = None
    # Dla legacy (raw w DB) FE może odtworzyć URL; dla v2 — None (sekret
    # nie jest odtwarzalny).
    share_url_suffix: Optional[str] = None


class CVShareTokenJobListItem(CVShareTokenListItem):
    """Link do CV w przekroju CAŁEJ pary (kandydat, rekrutacja).

    Link dla klienta powstaje na etapie SPRZED ruchu na „CV Wysłane", więc
    widok osoby na późniejszym etapie nie znajdzie go pod swoim ``stage_id``.
    Te same pola co lista per etap (bez sekretu) + etap, na którym link leży.
    """

    stage_id: int
    stage_name: str


class RecruitmentBrandedCvSummary(BaseModel):
    """Stan CV firmowego w przekroju CAŁEJ pary (kandydat, rekrutacja).

    Sfinalizowane CV firmowe leży na etapie SPRZED ruchu na „CV Wysłane" —
    bieżący wiersz etapu go nie ma, więc odznaka czytana per etap mówiła
    „brak". ``status == "none"`` = żaden etap pary nie ma CV firmowego;
    pozostałe pola są wtedy puste.
    """

    status: BrandedStatusLiteral = "none"
    stage_id: Optional[int] = None
    stage_name: Optional[str] = None
    finalized_at: Optional[datetime] = None


class CVShareTokensForRecruitment(BaseModel):
    """Linki do CV pary (kandydat, rekrutacja) + stan jej CV firmowego."""

    items: list[CVShareTokenJobListItem]
    branded_cv: RecruitmentBrandedCvSummary


class PublicCVView(BaseModel):
    """Public view brandowanego CV — TYLKO non-PII fields.

    Test `test_public_cv_no_pii_leakage` asercją sprawdza, że response NIE
    zawiera `email`, `phone`, `lastname`, `last_name`. Trzymaj się tej zasady.
    """

    candidate_first_name: Optional[str] = None
    job_title: Optional[str] = None
    cv_html: str
    expires_at: Optional[datetime] = None
