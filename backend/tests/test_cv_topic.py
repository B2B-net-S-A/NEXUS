"""Ikona „CV” w górnym pasku (16.10.2026, bez dzwonka) — kubełki ze stanu.

Czyste funkcje bez bazy: która karta jest „do poprawy”, która „u Delivery
Leada”, co liczy się do liczby na ikonie. Trasę sprawdza
`test_cv_topic_route.py` (Postgres w CI).
"""

from datetime import datetime, timezone

from app.services import cv_in_transit as transit_svc
from app.services.cv_topic import CvCheck, badge_for, recruiter_buckets

_NOW = datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)


def _row(kind: str, stage_id: int, **extra) -> transit_svc.TransitRow:
    return transit_svc.TransitRow(
        kind=kind,
        stage_id=stage_id,
        candidate_id=stage_id,
        candidate_name=f"Osoba {stage_id}",
        job_id=1,
        job_title="Tester",
        job_working_title=None,
        client_name="Klient Alfa",
        since=_NOW,
        **extra,
    )


def _transit() -> transit_svc.CvInTransit:
    return transit_svc.CvInTransit(
        returned=[
            _row(transit_svc.KIND_SENT_BACK, 1, remark="dopisz okres wypowiedzenia"),
            _row(transit_svc.KIND_REJECTED_BY_DL, 2),
            _row(transit_svc.KIND_CPRO_RETURNED, 3),
        ],
        in_review=[
            _row(transit_svc.KIND_IN_REVIEW, 4, qc_status="failed"),
            _row(transit_svc.KIND_IN_REVIEW, 5, qc_status="passed"),
            _row(transit_svc.KIND_IN_REVIEW, 6, qc_status="unchecked"),
            _row(transit_svc.KIND_CPRO_QUEUE, 7),
        ],
        sent=[_row(transit_svc.KIND_SENT, 8, actor_name="Paweł N.")],
    )


def _check(stage_id: int) -> CvCheck:
    return CvCheck(
        document_id=100 + stage_id,
        stage_id=stage_id,
        candidate_id=stage_id,
        candidate_name=f"Osoba {stage_id}",
        job_id=1,
        job_title="Tester",
        job_working_title=None,
        client_name=None,
        since=_NOW,
    )


def test_returned_and_failed_qc_are_to_fix_rejection_is_not():
    buckets = recruiter_buckets(_transit(), [_check(9)])
    assert [r.stage_id for r in buckets.to_fix] == [1, 3, 4]
    # Odrzucenie przez DL to ruch w rekrutacji, nie CV do poprawienia.
    assert all(r.stage_id != 2 for r in (*buckets.to_fix, *buckets.with_dl))


def test_qc_ok_running_and_cpro_queue_wait_with_the_delivery_lead():
    buckets = recruiter_buckets(_transit(), [])
    # QC w toku (unchecked) też czeka u DL — rekruter nie ma ruchu.
    assert [r.stage_id for r in buckets.with_dl] == [5, 6, 7]
    assert [r.stage_id for r in buckets.sent] == [8]


def test_badge_counts_only_what_waits_for_the_person():
    buckets = recruiter_buckets(_transit(), [_check(9)])
    # do sprawdzenia 1 + do poprawy 3; „u DL” i „wysłane” bez liczby.
    assert badge_for(recruiter=buckets, dl_to_send=0) == 4
    assert badge_for(recruiter=buckets, dl_to_send=2) == 6
    assert badge_for(recruiter=None, dl_to_send=2) == 2
    assert badge_for(recruiter=None, dl_to_send=0) == 0


def test_sent_today_starts_at_company_midnight():
    from app.services.cv_topic import _day_start

    # 23:30 UTC 16.10 to już 17.10 w Warszawie — „dziś” zaczyna się 17.10.
    late = datetime(2026, 10, 16, 23, 30, tzinfo=timezone.utc)
    start = _day_start(late)
    assert start.isoformat() == "2026-10-17T00:00:00+02:00"
