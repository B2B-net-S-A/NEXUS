"""Kroki w portalu Cpro (Playwright, sync). Jedna pozycja = jedna nowa sesja.

Selektory spisane z portalu 24.11.2026 (konto vendora, tylko odczyt):
logowanie ``#loginForm`` (``#user_username``, ``#user_password_PLAIN``),
konto w ``.vmsSideBarProfileUser``, request ``RequisitionController?action=view&id=<nr>``,
oferty ``OfferController?search=<nazwisko>`` (kolumny Offer|Offer date|Customer|
Request|Profile|Offered rate|Confirmed rate|Status|Status), profile przez
``#profileSearch`` + ``#searchButton`` (AJAX do ``#profileList``), „Add Consultant”
w oknie z ``#newConsultantForm``, formularz oferty ``form[action=OfferController]``
(``offer_*``, przyciski ``BUT_SaveAsDraft`` / ``BUT_SaveAndSubmit``), upload CV
``#cvUploadButton`` → ``#uploadCvForm``, suwaki jQuery UI ``#slider-match*`` z
ukrytymi ``offer_match*vend`` (0–10, 10 = „Perfect”).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional
from urllib.parse import quote, urljoin

from cpro_robot import rules
from cpro_robot.rules import Account

logger = logging.getLogger("cpro_robot")

STEP_TIMEOUT_MS = 30_000
MATCH_FIELDS = (
    "offer_matchoverallvend",
    "offer_matchcompanyvend",
    "offer_matchindustryvend",
    "offer_matchtechnologyvend",
    "offer_matchrolevend",
)


class Outcome(Exception):
    """Koniec pozycji z wynikiem do raportu."""

    def __init__(
        self,
        outcome: str,
        reason: Optional[str],
        message: str,
        *,
        cpro_status: Optional[str] = None,
        offer_url: Optional[str] = None,
    ):
        super().__init__(message)
        self.outcome = outcome
        self.reason = reason
        self.message = message
        self.cpro_status = cpro_status
        self.offer_url = offer_url


def _fail(reason: str, message: str) -> Outcome:
    return Outcome("failed", reason, message)


# Pola formularzy Cpro bywają ukryte albo przerobione skryptami portalu
# (przełączniki, edytor opisu, kalendarz) — Playwright odmawia wtedy fill/check
# i czeka do timeoutu (bieg 9). Wartość ustawia skrypt w stronie i wywołuje
# zdarzenia, na które czeka portal; wynik jest sprawdzany.
_PUT_JS = """(el, v) => {
  if (el.type === 'checkbox' || el.type === 'radio') {
    if (el.checked !== v) el.click();
    return el.checked === v;
  }
  el.value = v;
  el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
  const $ = window.jQuery;
  if ($) {
    const $el = $(el);
    if ($el.data('summernote')) $el.summernote('code', v);
    if ($el.data('selectpicker')) $el.selectpicker('refresh');
  }
  return String(el.value) === String(v);
}"""


def _put(scope: Any, name: str, value: Any, *, option: Optional[str] = None) -> None:
    """Wartość pola ``name`` (dla radia: ``option`` = wartość do zaznaczenia)."""

    selector = f"[name='{name}']" + (f"[value='{option}']" if option else "")
    loc = scope.locator(selector)
    if loc.count() == 0:
        raise _fail("other", f"Brak pola „{name}” w formularzu Cpro.")
    if not loc.first.evaluate(_PUT_JS, value):
        raise _fail("other", f"Cpro nie przyjął wartości pola „{name}”.")


def _js_click(loc: Any, what: str) -> None:
    """Klik skryptem: działa także na przycisku ukrytym albo przykrytym oknem."""

    if loc.count() == 0:
        raise _fail("other", f"Brak przycisku „{what}” w Cpro.")
    loc.first.evaluate("el => el.click()")


# Przycisk „Add Consultant” na requeście woła loadPopupLarge(ConsultantAddController…).
# Ten sam tekst ma ukryty link w menu, więc zwykły klik czekał do timeoutu (bieg 10).
_OPEN_ADD_CONSULTANT_JS = """(req) => {
  const a = [...document.querySelectorAll('a')].find(x =>
    /Add Consultant/.test(x.textContent || '') &&
    /ConsultantAddController/.test(x.getAttribute('onclick') || ''));
  if (a) { a.click(); return 'link'; }
  if (typeof window.loadPopupLarge === 'function') {
    window.loadPopupLarge('ConsultantAddController?action=add&navbacktoobject=requisition&requisition_requisitionid=' + req);
    return 'function';
  }
  return '';
}"""


class ItemRun:
    """Jedna pozycja zlecenia w świeżym kontekście przeglądarki."""

    def __init__(
        self,
        page: Any,
        base: str,
        item: dict[str, Any],
        account: Account,
        cv: bytes,
        submit: bool,
        dry_run: bool = False,
    ):
        self.page = page
        self.base = base  # https://nordea.onevms.se/nordea/
        self.item = item
        self.account = account
        self.cv = cv
        self.submit = submit
        self.candidate = item["candidate"]
        self.offer = item["offer"]
        self.request_no = str(item["request_number"])
        self.repair = bool(item.get("edit_existing_draft_only"))
        self.dry_run = dry_run
        self.saved = False
        self.cv_before: set[str] = set()
        self.step = "start"

    def before_write(self, what: str) -> None:
        """Próba bez zapisu (``CPRO_ROBOT_DRY_RUN``): stop przed pierwszą zmianą w Cpro."""

        if self.dry_run:
            raise _fail(
                "other",
                f"Próba bez zapisu: robot doszedł do kroku „{what}” i nic nie zmienił w Cpro.",
            )

    # --- konto -------------------------------------------------------------
    def login(self) -> None:
        self.step = "login"
        page = self.page
        page.goto(
            self.base.rsplit("/nordea/", 1)[0] + "/", wait_until="domcontentloaded"
        )
        page.locator("#user_username").fill(self.account.username)
        page.locator("#user_password_PLAIN").fill(self.account.password)
        page.locator(
            "#loginForm button", has_text=re.compile(r"^\s*login\s*$", re.I)
        ).first.click()
        page.wait_for_load_state("domcontentloaded")
        try:
            page.locator(".vmsSideBarProfileUser").first.wait_for(
                timeout=STEP_TIMEOUT_MS
            )
        except Exception as exc:
            raise _fail("login_failed", "Logowanie do Cpro nie powiodło się.") from exc
        self.verify_account()

    def verify_account(self) -> None:
        page = self.page
        if "/Login" in page.url or not page.url.startswith(self.base):
            raise Outcome(
                "skipped",
                "account_unverified",
                "Portal wylogował sesję w trakcie pozycji.",
            )
        label = page.locator(".vmsSideBarProfileUser").first
        if label.count() == 0:
            raise Outcome("skipped", "account_unverified", "Nie widać konta w portalu.")
        if rules.norm(label.inner_text()) != rules.norm(self.account.display_name):
            raise Outcome(
                "skipped",
                "account_mismatch",
                "Portal pokazuje inne konto niż wskazane.",
            )

    # --- request i oferty ---------------------------------------------------
    def open_request(self) -> None:
        self.step = "request"
        page = self.page
        page.goto(
            urljoin(
                self.base,
                f"vendor/RequisitionController?action=view&id={self.request_no}",
            )
        )
        page.wait_for_load_state("domcontentloaded")
        body = page.locator("body").inner_text()
        if f"({self.request_no})" not in body:
            raise _fail("request_not_found", "Nie ma takiego requestu w Cpro.")
        if rules.request_closed(body.split("Overview", 1)[0]):
            raise _fail("request_closed", "Request jest zamknięty albo anulowany.")

    def my_offers(self) -> list[rules.OfferRow]:
        self.step = "offers"
        page = self.page
        last = self.candidate["last_name"]
        page.goto(urljoin(self.base, f"vendor/OfferController?search={quote(last)}"))
        page.wait_for_load_state("domcontentloaded")
        raw = page.evaluate(
            """() => {
              const t = [...document.querySelectorAll('table')].find(x => /Offered rate/.test(x.textContent));
              if (!t) return [];
              return [...t.querySelectorAll('tbody tr')].map(tr => ({
                cells: [...tr.children].map(td => td.innerText.trim()),
                view: [...tr.querySelectorAll('a')].map(a => a.href).find(h => /action=view/.test(h)) || null,
              }));
            }"""
        )
        rows = [rules.offer_row(r["cells"], r["view"]) for r in raw]
        return rules.offers_of(
            [r for r in rows if r],
            self.request_no,
            self.candidate["first_name"],
            self.candidate["last_name"],
        )

    def open_draft_edit(self, row: rules.OfferRow) -> None:
        self.step = "draft_edit"
        href = (
            self.page.evaluate(
                """(id) => [...document.querySelectorAll('a[href*="action=edit"]')]
                  .map(a => a.href)
                  .find(h => new URL(h).searchParams.getAll('id').includes(String(id))) || ''""",
                row.offer_id,
            )
            if row.offer_id is not None
            else ""
        )
        if not href:
            raise _fail("draft_not_found", "Nie da się otworzyć szkicu do edycji.")
        self.page.goto(href)
        self._wait_offer_form()
        heading = self.page.locator("h1, h2, h3").filter(has_text="Change Offer").first
        title = heading.inner_text() if heading.count() else ""
        who = f"{self.candidate['first_name']} {self.candidate['last_name']}"
        if not rules.norm(title).startswith(f"change offer: {rules.norm(who)}"):
            raise _fail(
                "draft_identity_mismatch", "Otwarty szkic nie należy do tej osoby."
            )

    # --- profil i nowa oferta -----------------------------------------------
    def open_offer_from_profile(self, *, created: bool = False) -> None:
        """Oferta z profilu na requeście; bez profilu — nowy konsultant i drugi raz.

        ``created``: konsultant właśnie zapisany razem z CV, więc bez drugiego
        uploadu i bez kolejnego zakładania, gdy profilu nadal nie widać.
        """

        self.step = "profile"
        page = self.page
        self.open_request()
        page.locator("#profileSearch").fill(
            f"{self.candidate['first_name']} {self.candidate['last_name']}"
        )
        # Wyszukiwarka to AJAX (loadDiv → ProfileController…dosearchwithjq);
        # czekamy na jej odpowiedź, a nie tylko na ciszę sieci.
        try:
            with page.expect_response(
                lambda r: "dosearchwithjq" in r.url, timeout=STEP_TIMEOUT_MS
            ):
                page.locator("#searchButton").click()
        except Exception:
            pass
        page.wait_for_load_state("networkidle")
        found = page.evaluate(
            """() => ({
              profiles: [...document.querySelectorAll('#profileList tbody tr')].map(tr => ({
                name: (tr.children[1] || {innerText: ''}).innerText.trim(),
                offer: [...tr.querySelectorAll('a')].map(a => a.href).find(h => /action=add/.test(h)) || null,
              })),
              orphans: [...document.querySelectorAll('#consultantList tbody tr')].map(tr => tr.innerText.trim()),
            })"""
        )
        first, last = self.candidate["first_name"], self.candidate["last_name"]
        mine = [
            p for p in found["profiles"] if rules.same_person(p["name"], first, last)
        ]
        if len(mine) > 1:
            raise _fail("ambiguous_profile", "Kilka profili o tym imieniu i nazwisku.")
        if mine:
            if not mine[0]["offer"]:
                raise _fail("other", "Profil bez przycisku „Offer…”.")
            page.goto(mine[0]["offer"])
            self._wait_offer_form()
            if not created:
                self.upload_cv_unless_present()
            return
        orphan = any(
            rules.norm(f"{first} {last}") in rules.norm(t) for t in found["orphans"]
        )
        if created:
            raise _fail(
                "other",
                "Po zapisie konsultanta nie widać jego profilu na requeście "
                f"(profile w wynikach: {len(found['profiles'])}, "
                f"bez profilu: {'tak' if orphan else 'nie'}, "
                f"na liście Consultants: {self.consultants_named()}).",
            )
        if orphan:
            raise _fail(
                "other", "Konsultant jest w Cpro bez profilu; dodaj profil ręcznie."
            )
        # Bez profilu na requeście nie zakładamy konsultanta, który już jest
        # w Cpro (np. zapisany przez poprzedni bieg) — duplikat widzi Nordea.
        existing = self.consultants_named()
        if existing:
            raise _fail(
                "other",
                f"W Cpro jest już konsultant o tym imieniu i nazwisku ({existing}), "
                "ale bez profilu na tym requeście; robot nie zakłada drugiego.",
            )
        self.open_request()  # okno „Add Consultant” otwiera się ze strony requestu
        self.add_consultant()
        self.open_offer_from_profile(created=True)

    def consultants_named(self) -> int:
        """Ilu konsultantów o tym imieniu i nazwisku ma lista Consultants vendora."""

        page = self.page
        last = self.candidate["last_name"]
        page.goto(
            urljoin(self.base, f"vendor/ConsultantController?search={quote(last)}")
        )
        page.wait_for_load_state("domcontentloaded")
        rows = page.evaluate(
            "() => [...document.querySelectorAll('table tbody tr')].map(tr => tr.innerText)"
        )
        who = rules.norm(f"{self.candidate['first_name']} {last}")
        return sum(1 for text in rows if who in rules.norm(text))

    def add_consultant(self) -> None:
        self.step = "add_consultant"
        self.before_write("Add Consultant")
        page = self.page
        self.step = "add_consultant:open"
        if not page.evaluate(_OPEN_ADD_CONSULTANT_JS, self.request_no):
            raise _fail("other", "Nie da się otworzyć okna „Add Consultant” w Cpro.")
        form = page.locator("#newConsultantForm")
        form.wait_for(state="attached", timeout=STEP_TIMEOUT_MS)
        self.step = "add_consultant:fields"
        _put(form, "consultant_firstname", self.candidate["first_name"])
        _put(form, "consultant_lastname", self.candidate["last_name"])
        options = form.locator("select[name=consultant_country] option").evaluate_all(
            "os => os.map(o => [o.value, o.text.trim()])"
        )
        country = rules.country_option(
            [tuple(o) for o in options], self.candidate.get("citizenship") or ""
        )
        if country is None:
            raise _fail("other", "Nie da się wybrać kraju obywatelstwa z listy Cpro.")
        _put(form, "consultant_country", country)
        _put(form, "consultant_gender", True, option="UNKNOWN")
        _put(form, "consultant_consultantemployment", True, option="SUBCONTRACTOR")
        _put(form, "consultant_subcontractorcompany", rules.SUBCONTRACTOR_COMPANY)
        form.locator("[name=cv_filename]").set_input_files(self._cv_file())
        _put(
            form, "profile_description", self.candidate.get("profile_description") or ""
        )
        # Formularz konsultanta ma własny Save (#saveButton); „Offer…” w tym
        # oknie należy do innego formularza (bieg 11). Najpierw walidacja HTML
        # — przeglądarka po cichu nie wysłałaby niepełnego formularza.
        invalid = form.evaluate(
            "f => [...f.elements].filter(e => e.willValidate && !e.checkValidity()).map(e => e.name)"
        )
        if invalid:
            raise _fail(
                "other",
                "Formularz konsultanta niekompletny: "
                + ", ".join(sorted(set(invalid)))[:200],
            )
        self.verify_account()
        self.step = "add_consultant:save"
        _js_click(form.locator("#saveButton"), "Save")
        self.saved = True  # od tej chwili konsultant może już istnieć w Cpro
        page.wait_for_load_state("networkidle")
        rejected = page.evaluate(
            """() => [...document.querySelectorAll('#newConsultantForm .is-invalid')].map(e => e.name)"""
        )
        if rejected:
            self.saved = False
            raise _fail(
                "other",
                "Cpro odrzucił formularz konsultanta: "
                + ", ".join(sorted(set(rejected)))[:200],
            )

    # --- formularz oferty ---------------------------------------------------
    def _wait_offer_form(self) -> None:
        self.page.wait_for_load_state("domcontentloaded")
        try:
            self.page.locator(
                "form[action=OfferController] [name=offer_offerinrate]"
            ).wait_for(timeout=STEP_TIMEOUT_MS)
        except Exception as exc:
            raise _fail(
                "other", f"Portal nie otworzył formularza oferty (krok {self.step})."
            ) from exc

    def _cv_file(self) -> dict[str, Any]:
        return {
            "name": self.offer["cv_file_name"],
            "mimeType": "application/pdf",
            "buffer": self.cv,
        }

    def upload_cv(self) -> None:
        self.step = "upload_cv"
        self.before_write("Upload new CV")
        page = self.page
        self.cv_before = set(
            page.locator("input[name=offer_cvids]").evaluate_all(
                "bs => bs.map(b => b.value)"
            )
        )
        _js_click(page.locator("#cvUploadButton"), "Upload new CV")
        form = page.locator("#uploadCvForm")
        form.wait_for(state="attached", timeout=STEP_TIMEOUT_MS)
        form.locator("[name=cv_filename]").set_input_files(self._cv_file())
        lang = form.locator("select[name=cv_language] option").evaluate_all(
            "os => (os.find(o => /^EN\\b/.test(o.text.trim())) || {}).value || ''"
        )
        if lang:
            _put(form, "cv_language", lang)
        self.verify_account()
        _js_click(form.locator("button[type=submit], input[type=submit]"), "Upload")
        self._wait_offer_form()

    def upload_cv_unless_present(self) -> None:
        """Szkic albo profil z poprzedniego biegu ma już ten PDF — bez drugiego uploadu."""

        labels = self.page.evaluate(
            """() => [...document.querySelectorAll('input[name=offer_cvids]')].map(b => {
              const l = b.id && document.querySelector('label[for="' + b.id + '"]');
              return (l ? l.innerText : (b.parentElement || {}).innerText || '').trim();
            })"""
        )
        if any(rules.cv_label_matches(t, self.offer["cv_file_name"]) for t in labels):
            self.step = "cv_reuse"
            return
        self.upload_cv()

    def select_only_new_cv(self) -> None:
        self.step = "cv_select"
        boxes = self.page.evaluate(
            """() => [...document.querySelectorAll('input[name=offer_cvids]')].map(b => {
              const l = b.id && document.querySelector('label[for="' + b.id + '"]');
              return {value: b.value, label: (l ? l.innerText : (b.parentElement || {}).innerText || '').trim()};
            })"""
        )
        mine = [
            b
            for b in boxes
            if rules.cv_label_matches(b["label"], self.offer["cv_file_name"])
            and b["value"] not in self.cv_before
        ]
        if not mine:
            raise _fail(
                "cv_not_opening", "Wgrany PDF nie pojawił się na liście CV oferty."
            )
        keep = max(
            mine, key=lambda b: int(b["value"]) if str(b["value"]).isdigit() else -1
        )["value"]
        for box in boxes:
            _put(self.page, "offer_cvids", box["value"] == keep, option=box["value"])

    def fill_offer(self) -> None:
        self.step = "offer_fields"
        page = self.page
        form = page.locator("form[action=OfferController]")
        frame = form.locator("select[name=offer_frameagreementid]")
        if frame.input_value() in ("", "0"):
            values = frame.locator("option").evaluate_all(
                "os => os.map(o => o.value).filter(v => v && v !== '0')"
            )
            if len(values) != 1:
                raise _fail("other", "Nie ma jednej aktywnej umowy ramowej do wyboru.")
            _put(form, "offer_frameagreementid", values[0])
        _put(form, "offer_offerinrate", str(self.offer["rate"]).replace(".", ","))
        pln = form.locator("select[name=offer_currencyid] option").evaluate_all(
            "os => (os.find(o => /^PLN\\b/.test(o.text.trim())) || {}).value || ''"
        )
        if not pln:
            raise _fail("other", "Brak waluty PLN w formularzu.")
        _put(form, "offer_currencyid", pln)
        _put(form, "offer_motivationvendor", self.offer["motivation"])
        _put(form, "offer_availablefromdate", self.offer["available_from"])
        _put(form, "offer_availablecomments", self.offer["physical_location"])
        consultant, employee = self._former()
        _put(
            form, "offer_hasbeenconsultant", True, option="YES" if consultant else "NO"
        )
        _put(form, "offer_hasbeenemployee", True, option="YES" if employee else "NO")
        _put(form, "consultant_consultantemployment", True, option="SUBCONTRACTOR")
        _put(form, "consultant_subcontractorcompany", rules.SUBCONTRACTOR_COMPANY)
        _put(form, "offer_subcontractorrate", "0,00")
        _put(form, "orgconsultant_isuktaxresident", True, option="NO")
        page.evaluate(
            """(fields) => {
              fields.forEach(n => document.querySelectorAll('input[name="' + n + '"]').forEach(i => { i.value = '10.0'; }));
              if (window.jQuery) jQuery('[id^=slider-match]').each(function () { try { jQuery(this).slider('value', 10); } catch (e) {} });
            }""",
            list(MATCH_FIELDS),
        )

    def _former(self) -> tuple[bool, bool]:
        consultant = self.offer.get("former_consultant")
        employee = self.offer.get("former_employee")
        if isinstance(consultant, bool) and isinstance(employee, bool):
            return consultant, employee
        from_cv = rules.former_from_cv_text(_pdf_text(self.cv))
        if from_cv is None:
            raise _fail(
                "other",
                "Nordea w CV: „Former consultant/employee” do rozstrzygnięcia ręcznie.",
            )
        return (
            consultant if isinstance(consultant, bool) else from_cv[0],
            employee if isinstance(employee, bool) else from_cv[1],
        )

    def save_draft(self) -> None:
        """Save as draft. Cpro zapisuje w tle, bez przejścia na inną stronę
        (biegi 14–22): dowodem zapisu jest dopiero lista ofert w ``confirm_draft``."""

        self.step = "save"
        self.before_write("Save as draft")
        page = self.page
        form = page.locator("form[action=OfferController]")
        invalid = form.first.evaluate(
            "f => [...f.elements].filter(e => e.willValidate && !e.checkValidity()).map(e => e.name)"
        )
        if invalid:
            raise _fail(
                "other",
                "Formularz oferty niekompletny: "
                + ", ".join(sorted(set(invalid)))[:200],
            )
        self.verify_account()
        _js_click(
            form.locator("button[name=BUT_SaveAsDraft]"),
            "Save as draft",
        )
        self.saved = True
        try:
            page.wait_for_load_state("networkidle", timeout=STEP_TIMEOUT_MS)
        except Exception:
            pass
        rejected = page.evaluate(
            """() => [...document.querySelectorAll('form[action=OfferController] .is-invalid')].map(e => e.name)"""
        )
        if rejected:
            raise _fail(
                "draft_unconfirmed",
                "Cpro oznaczył pola oferty jako błędne: "
                + ", ".join(sorted(set(rejected)))[:200],
            )

    # --- potwierdzenie --------------------------------------------------------
    def confirm_draft(self) -> Outcome:
        self.step = "confirm"
        drafts = [r for r in self.my_offers() if rules.is_draft(r)]
        if len(drafts) != 1 or drafts[0].offer_id is None:
            raise _fail(
                "draft_unconfirmed",
                "Po zapisie nie widać dokładnie jednego szkicu tej osoby.",
            )
        url = urljoin(
            self.base, f"vendor/OfferController?action=view&id={drafts[0].offer_id}"
        )
        self.page.goto(url)
        self.page.wait_for_load_state("domcontentloaded")
        body = self.page.locator("body").inner_text()
        if not self.repair and not rules.saved_values_visible(
            body, self.offer["rate"], self.offer["available_from"]
        ):
            raise _fail(
                "draft_unconfirmed", "Szkic nie pokazuje zapisanej stawki albo daty."
            )
        link = self.page.locator(
            "a", has_text=re.compile(re.escape(self.offer["cv_file_name"][:-4]), re.I)
        ).first
        if link.count() == 0:
            raise _fail("cv_not_opening", "W szkicu nie widać wgranego PDF.")
        href = link.get_attribute("href") or ""
        resp = (
            self.page.request.get(urljoin(self.page.url, href))
            if href and not href.startswith("javascript")
            else None
        )
        if resp is not None and (
            not resp.ok
            or not resp.body().startswith(b"%PDF-")
            or _pdf_pages(resp.body()) < 1
        ):
            raise _fail("cv_not_opening", "PDF w szkicu nie otwiera się.")
        return Outcome(
            "draft",
            None,
            "Szkic zapisany przez robota NEXUSA i potwierdzony po ponownym otwarciu.",
            cpro_status="DRAFT",
            offer_url=url,
        )

    # --- przebieg ---------------------------------------------------------------
    def run(self) -> Outcome:
        if self.submit:
            raise _fail(
                "other",
                "Robot NEXUSA zapisuje tylko szkice; wysyłka zostaje u człowieka.",
            )
        self.login()
        self.open_request()
        mine = self.my_offers()
        sent = [r for r in mine if not rules.is_draft(r)]
        drafts = [r for r in mine if rules.is_draft(r)]
        if sent and not drafts:
            raise Outcome(
                "skipped",
                "already_offered",
                "Osoba ma już ofertę na tym requeście.",
                cpro_status=sent[0].status[:60],
            )
        if self.repair:
            if not drafts:
                raise _fail("draft_not_found", "Nie ma szkicu tej osoby do poprawy.")
            if len(drafts) > 1:
                raise _fail("ambiguous_draft", "Kilka szkiców tej osoby na requeście.")
            self.open_draft_edit(drafts[0])
            self.upload_cv()
            self.select_only_new_cv()
            self.save_draft()
            return self.confirm_draft()
        if len(drafts) > 1:
            raise _fail("ambiguous_draft", "Kilka szkiców tej osoby na requeście.")
        if drafts:
            self.open_draft_edit(drafts[0])
            self.upload_cv_unless_present()
        else:
            self.open_offer_from_profile()
        self.select_only_new_cv()
        self.fill_offer()
        self.save_draft()
        return self.confirm_draft()


def _pdf_doc(data: bytes) -> Any:
    import pypdfium2  # w obrazie robota; import leniwy dla testów bez niego

    return pypdfium2.PdfDocument(data)


def _pdf_pages(data: bytes) -> int:
    try:
        return len(_pdf_doc(data))
    except Exception:
        return 0


def _pdf_text(data: bytes) -> str:
    try:
        doc = _pdf_doc(data)
        return "\n".join(
            doc[i].get_textpage().get_text_range() for i in range(len(doc))
        )
    except Exception:
        return ""
