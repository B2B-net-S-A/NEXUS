"""Ogłoszenie dla JustJoin.IT / RocketJobs (0381) — czyste funkcje, bez bazy.

Pilnuje reguł dostawcy (limity umiejętności per portal, widełki ≤ 3×,
hybryda 1–4 dni, B2B netto) i białej listy treści: do portalu nie trafia
nic spoza ``public_job_payload`` (klient, stawka), a tekst jest escapowany.
"""

from __future__ import annotations

from app.services.job_portals import jjit_payload as p


def _job(**overrides):
    job = {
        "slug": "java-dev",
        "title": "Java Developer",
        "subtitle": "rozwój platformy płatności w sektorze bankowym",
        "about": "Pierwszy akapit.\n\nDrugi <script>alert(1)</script> akapit.",
        "must": [{"name": n, "note": None} for n in ("Java", "Spring", "Kafka")],
        "nice": ["Kubernetes", "java"],
        "params": {"city": "Warszawa", "start": "ASAP", "duration": "12 mies."},
        "show": {"must": True, "nice": True, "params": True, "process": True},
    }
    job.update(overrides)
    return job


def _options(**overrides):
    options = {
        "category": "java",
        "experience_level": "senior",
        "working_time": "full_time",
        "workplace_type": "hybrid",
        "office_days": 2,
        "city": "Warszawa",
        "salary": None,
    }
    options.update(overrides)
    return p.normalize_options(options)


def test_default_options_map_job_fields_and_leave_category_to_a_human():
    options = p.default_options(
        {
            "city": "Kraków",
            "remote_policy": "onsite",
            "onsite_days_per_week": 5,
            "seniority": "architect",
        },
        work_mode="parttime",
    )
    assert options == {
        "category": None,
        "experience_level": "senior",
        "working_time": "part_time",
        "workplace_type": "office",
        "office_days": None,
        "city": "Kraków",
        "salary": None,
    }


def test_hybrid_keeps_office_days_and_schedule_sums_to_five():
    options = p.default_options(
        {"remote_policy": "hybrid", "onsite_days_per_week": 3}, work_mode=None
    )
    assert options["office_days"] == 3
    assert options["working_time"] == "full_time"
    assert p.hybrid_schedule(options) == {"officeDays": 3, "remoteDays": 2}
    assert (
        p.hybrid_schedule(_options(workplace_type="remote", office_days=None)) is None
    )


def test_valid_listing_has_no_problems():
    assert p.validate("rocketjobs", _job(), _options()) == []


def test_missing_fields_are_listed_in_polish():
    problems = p.validate(
        "justjoinit",
        _job(must=[], about=None, subtitle=None, nice=[], params={}),
        p.normalize_options({}),
    )
    joined = " | ".join(problems)
    for fragment in (
        "kategorię",
        "poziom",
        "wymiar",
        "tryb pracy",
        "miasto",
        "must-have",
        "Opis publiczny",
    ):
        assert fragment in joined


def test_salary_rules():
    assert (
        p.validate("rocketjobs", _job(), _options(salary={"from": 100, "to": 300}))
        == []
    )
    too_wide = p.validate(
        "rocketjobs", _job(), _options(salary={"from": 100, "to": 301})
    )
    assert any("3 razy" in m for m in too_wide)
    reversed_ = p.validate(
        "rocketjobs", _job(), _options(salary={"from": 200, "to": 100})
    )
    assert any("mniejsza" in m for m in reversed_)
    half = p.validate("rocketjobs", _job(), _options(salary={"from": 100}))
    assert any("obie kwoty" in m for m in half)


def test_office_days_only_with_hybrid_and_within_range():
    wrong_mode = p.validate("rocketjobs", _job(), _options(workplace_type="remote"))
    assert any("tylko przy pracy hybrydowej" in m for m in wrong_mode)
    out_of_range = p.validate("rocketjobs", _job(), _options(office_days=5))
    assert any("od 1 do 4" in m for m in out_of_range)


def test_skill_limits_per_board():
    many = [{"name": f"Skill{i}", "note": None} for i in range(15)]
    nice = [f"Nice{i}" for i in range(12)]
    must_jj, nice_jj = p.skill_split("justjoinit", _job(must=many, nice=nice))
    assert len(must_jj) == 10 and nice_jj == []
    must_rj, nice_rj = p.skill_split("rocketjobs", _job(must=many, nice=nice))
    assert len(must_rj) == 8 and len(nice_rj) == 8


def test_nice_duplicate_of_must_is_dropped():
    _must, nice = p.skill_split("rocketjobs", _job())
    assert nice == ["Kubernetes"]


def test_body_escapes_text_and_lists_nice_even_on_jjit():
    body = p.build_body(_job())
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
    assert "<h3>Mile widziane</h3>" in body
    assert "<li>Kubernetes</li>" in body
    assert body.count("<p>") == 3  # podtytuł + dwa akapity


def test_body_respects_hidden_sections():
    body = p.build_body(_job(show={"must": False, "nice": False, "params": False}))
    assert "Wymagania" not in body and "Mile widziane" not in body
    assert "Szczegóły" not in body


def test_create_body_shape_and_skill_matching():
    skills = {
        p.skill_key("Java"): {"id": "s-java", "name": "Java"},
        p.skill_key("spring"): {"id": "s-spring", "name": "Spring"},
        p.skill_key("Kubernetes"): {"id": "s-k8s", "name": "Kubernetes"},
    }
    body = p.create_body(
        "rocketjobs",
        title="Java Developer",
        job=_job(),
        options=_options(salary={"from": 150, "to": 190, "unit": "hour"}),
        apply_url="https://kariera.dynaminds.pl/r/java-dev",
        skill_ids=skills,
        payment={"type": "Code", "id": "KOD-1"},
        external_id="nexus-posting-7",
    )
    assert body["jobBoard"] == "rocketjobs"
    assert body["apply"] == {
        "url": "https://kariera.dynaminds.pl/r/java-dev",
        "email": None,
    }
    assert body["externalId"] == "nexus-posting-7"
    assert body["category"] == "java"
    assert body["hybridWorkSchedule"] == {"officeDays": 2, "remoteDays": 3}
    assert body["employmentTypes"] == [
        {
            "type": "b2b",
            "currency": "PLN",
            "amountType": "net",
            "salary": {"from": 150.0, "to": 190.0, "unit": "hour"},
        }
    ]
    reqs = [(r["skillName"], r["required"], r["ordinal"]) for r in body["requirements"]]
    # Kafka nie ma id z `PUT /skills` — pomijana, reszta w kolejności.
    assert reqs == [("Java", True, 0), ("Spring", True, 1), ("Kubernetes", False, 2)]
    assert body["locations"][0]["city"] == "Warszawa"


def test_create_body_without_salary_sends_null():
    body = p.create_body(
        "justjoinit",
        title="T",
        job=_job(),
        options=_options(),
        apply_url="https://x/r/a",
        skill_ids={},
        payment={"type": "Code", "id": "K"},
        external_id="nexus-posting-1",
    )
    assert body["employmentTypes"][0]["salary"] is None
    assert body["requirements"] == []


def test_update_body_carries_fields_put_requires():
    current = {
        "informationClause": "Klauzula",
        "contact": {"name": "A", "email": "a@b.pl", "phone": "1"},
        "publicTags": [{"key": "x"}],
    }
    body = p.update_body(
        "rocketjobs",
        current=current,
        job=_job(),
        options=_options(),
        apply_url="https://x/r/a",
        skill_ids={},
    )
    for forbidden in ("jobBoard", "title", "payment", "externalId", "category"):
        assert forbidden not in body
    assert body["categories"] == ["java"]
    assert body["informationClause"] == "Klauzula"
    assert body["contact"]["email"] == "a@b.pl"
    assert body["publicTags"] == [{"key": "x"}]


def test_skill_key_keeps_cpp_and_csharp_apart():
    assert p.skill_key("C++") != p.skill_key("C#") != p.skill_key("C")
    assert p.skill_key("Node.js") == p.skill_key("nodejs")


def test_pick_payment_prefers_codes_expiring_first_then_subscription():
    now = "2026-09-25T00:00:00+00:00"
    balance = {
        "codes": [
            {
                "name": "LATER",
                "maxUsage": 5,
                "currentUsage": 1,
                "expiresAt": "2027-01-01",
            },
            {
                "name": "SOON",
                "maxUsage": 5,
                "currentUsage": 4,
                "expiresAt": "2026-10-01",
            },
            {
                "name": "USED",
                "maxUsage": 1,
                "currentUsage": 1,
                "expiresAt": "2026-10-01",
            },
            {
                "name": "OLD",
                "maxUsage": 5,
                "currentUsage": 0,
                "expiresAt": "2026-01-01",
            },
            {"name": "JJ", "jobBoard": "justjoinit", "maxUsage": 5, "currentUsage": 0},
        ],
        "subscriptions": [
            {"id": "sub-1", "isActive": True, "maxUsage": 10, "currentUsage": 2}
        ],
    }
    assert p.pick_payment("rocketjobs", balance, now_iso=now) == {
        "type": "Code",
        "id": "SOON",
    }
    no_codes = {"codes": [], "subscriptions": balance["subscriptions"]}
    assert p.pick_payment("rocketjobs", no_codes, now_iso=now) == {
        "type": "Subscription",
        "id": "sub-1",
    }
    inactive = {
        "subscriptions": [
            {"id": "s", "isActive": False, "maxUsage": 9, "currentUsage": 0}
        ]
    }
    assert p.pick_payment("rocketjobs", inactive, now_iso=now) is None


def test_normalize_options_drops_unknown_keys_and_bad_values():
    options = p.normalize_options(
        {
            "category": "  java  ",
            "workplace_type": "moon",
            "office_days": "x",
            "salary": {"from": "1 000,50", "to": "2000", "unit": "week"},
            "client": "Nordea",
        }
    )
    assert set(options) == set(p.OPTION_KEYS)
    assert options["category"] == "java"
    assert options["workplace_type"] is None
    assert options["office_days"] is None
    assert options["salary"] == {"from": 1000.5, "to": 2000.0, "unit": "month"}
