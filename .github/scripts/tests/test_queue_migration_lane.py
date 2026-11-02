import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "queue_migration_lane", ROOT / ".github/scripts/queue_migration_lane.py"
)
QML = importlib.util.module_from_spec(SPEC)
sys.modules["queue_migration_lane"] = QML
SPEC.loader.exec_module(QML)

MIGRATION = "backend/alembic/versions/0616_x.py"


def node(
    number,
    files=(MIGRATION,),
    labels=(),
    queue=None,
    armed=False,
    checks="SUCCESS",
    mergeable="MERGEABLE",
    draft=False,
    fork=False,
):
    return {
        "id": f"PR_{number}",
        "number": number,
        "isDraft": draft,
        "isCrossRepository": fork,
        "mergeable": mergeable,
        "headRefOid": f"sha{number}",
        "labels": {"nodes": [{"name": n} for n in labels]},
        "autoMergeRequest": {"enabledAt": "2026-10-28T23:00:00Z"} if armed else None,
        "mergeQueueEntry": {"position": queue} if queue else None,
        "files": {"nodes": [{"path": p} for p in files]},
        "commits": {
            "nodes": [
                {"commit": {"statusCheckRollup": {"state": checks} if checks else None}}
            ]
        },
    }


def pr(
    number,
    queue=None,
    armed=False,
    waiting=False,
    healthy=True,
    fresh=True,
    parent=None,
    tail=None,
    orphan=False,
):
    return QML.Pr(
        number,
        f"PR_{number}",
        queue,
        armed,
        waiting,
        healthy,
        fresh,
        parent,
        tail,
        orphan,
    )


def source(revision, down):
    return f'"""x"""\nrevision: str = "{revision}"\ndown_revision = "{down}"\n'


class FakeGh:
    def __init__(self, pages, main_files="", blobs=None):
        self.pages = list(pages)
        self.main_files = main_files
        self.blobs = blobs or {}
        self.calls = []

    def __call__(self, *args, stdin=None):
        self.calls.append(args)
        if "Accept: application/vnd.github.raw" in args:
            return self.blobs.get(args[1].split("?ref=")[0].rsplit("/", 1)[-1], "")
        if "contents/backend/alembic/versions" in args[1]:
            return self.main_files
        if args[:2] == ("api", "graphql") and "query=mutation" not in args[3]:
            nodes = self.pages.pop(0) if self.pages else []
            more = bool(self.pages)
            return json.dumps(
                {
                    "data": {
                        "repository": {
                            "pullRequests": {
                                "pageInfo": {"hasNextPage": more, "endCursor": "c1"},
                                "nodes": nodes,
                            }
                        }
                    }
                }
            )
        return ""

    def mutations(self):
        return [
            c
            for c in self.calls
            if "contents/backend/alembic/versions" not in c[1]
            and (c[:2] != ("api", "graphql") or "query=mutation" in c[3])
        ]


def quiet(fn, *args, **kwargs):
    with redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


class ParseTest(unittest.TestCase):
    def test_only_open_migration_prs_take_part(self):
        prs = QML.parse_prs(
            [
                node(1),
                node(2, files=("backend/app/main.py",)),
                node(3, files=("backend/alembic/versions/README",)),
                node(4, draft=True),
                node(5, fork=True),
                node(6, labels=("wstrzymaj",)),
            ]
        )
        self.assertEqual([p.number for p in prs], [1])

    def test_reads_queue_auto_merge_label_and_health(self):
        prs = {
            p.number: p
            for p in QML.parse_prs(
                [
                    node(1, queue=3, armed=True),
                    node(2, labels=("czeka-na-migracje",)),
                    node(3, checks="FAILURE"),
                    node(4, mergeable="CONFLICTING"),
                    node(5, checks=None),
                ]
            )
        }
        self.assertEqual(prs[1].queue_position, 3)
        self.assertTrue(prs[1].armed)
        self.assertTrue(prs[2].waiting)
        self.assertFalse(prs[3].healthy)
        self.assertFalse(prs[4].healthy)
        self.assertTrue(prs[5].healthy, "Brak checków to nie czerwień.")

    def test_migration_numbered_at_or_below_main_is_not_fresh(self):
        prs = {
            p.number: p
            for p in QML.parse_prs(
                [
                    node(1, files=("backend/alembic/versions/0631_a.py",)),
                    node(2, files=("backend/alembic/versions/0632_b.py",)),
                    node(3, files=("backend/alembic/versions/0630_c.py",)),
                ],
                main_top=631,
            )
        }
        self.assertFalse(prs[1].fresh)
        self.assertTrue(prs[2].fresh)
        self.assertFalse(prs[3].fresh)

    def test_unknown_main_top_keeps_everyone_fresh(self):
        self.assertTrue(QML.parse_prs([node(1)])[0].fresh)


class PlanTest(unittest.TestCase):
    def test_first_in_queue_keeps_the_lane_the_rest_leave(self):
        plan = QML.plan_lane(
            [
                pr(10, queue=4, armed=True),
                pr(11, queue=2, armed=True),
                pr(12, armed=True),
                pr(13, armed=True, healthy=False),
            ]
        )
        self.assertEqual(plan.active, 11)
        self.assertEqual(plan.dequeue, (10,))
        self.assertEqual(plan.park, (10, 12, 13))
        self.assertIsNone(plan.promote)

    def test_red_armed_pr_is_disarmed_while_the_lane_is_busy(self):
        # #2916, 02.11.2026: uzbrojony z etykietą i czerwonym checkiem. Po
        # zazielenieniu GitHub sam wrzuciłby go do kolejki obok aktywnego.
        plan = QML.plan_lane(
            [
                pr(70, queue=1, armed=True),
                pr(71, armed=True, waiting=True, healthy=False),
            ]
        )
        self.assertEqual(plan.active, 70)
        self.assertEqual(plan.park, (71,))
        self.assertEqual(plan.dequeue, ())

    def test_without_queue_the_oldest_ready_pr_is_active(self):
        plan = QML.plan_lane(
            [pr(20, armed=True), pr(21, armed=True), pr(22, waiting=True)]
        )
        self.assertEqual(plan.active, 20)
        self.assertEqual(plan.park, (21,))
        self.assertEqual(plan.dequeue, ())

    def test_red_armed_pr_does_not_block_the_lane(self):
        plan = QML.plan_lane([pr(30, armed=True, healthy=False), pr(31, waiting=True)])
        self.assertIsNone(plan.active)
        self.assertEqual(plan.promote, 31)

    def test_free_lane_promotes_the_oldest_healthy_waiting_pr(self):
        plan = QML.plan_lane(
            [
                pr(40, waiting=True, healthy=False),
                pr(41, waiting=True),
                pr(42, waiting=True),
            ]
        )
        self.assertEqual(plan.promote, 41)

    def test_free_lane_skips_waiting_pr_not_yet_rechained(self):
        # 02.11.2026: pas dał kolej #2897 w tej samej chwili, gdy #2889 wszedł
        # na main. PR był zielony, więc trafił do kolejki z dwiema głowami,
        # a push z przepięciem odbił się od GH006.
        plan = QML.plan_lane([pr(80, waiting=True, fresh=False), pr(81, waiting=True)])
        self.assertEqual(plan.promote, 81)

    def test_free_lane_waits_when_nobody_is_rechained_yet(self):
        plan = QML.plan_lane([pr(82, waiting=True, fresh=False)])
        self.assertIsNone(plan.promote)
        self.assertEqual(
            plan.rechain, True, "Bez pushu na main nic innego nie przepnie."
        )

    def test_active_pr_with_the_wait_label_loses_it(self):
        plan = QML.plan_lane([pr(50, queue=1, armed=True, waiting=True)])
        self.assertEqual(plan.active, 50)
        self.assertEqual(plan.unlabel, (50,))

    def test_nothing_to_do(self):
        self.assertEqual(QML.plan_lane([pr(60)]), QML.Plan(active=None))
        self.assertEqual(QML.plan_lane([]), QML.Plan(active=None))


class ChainTest(unittest.TestCase):
    def a(self, **kw):
        return pr(1, queue=1, armed=True, tail="0634_a", **kw)

    def test_second_slot_goes_to_the_green_pr_stacked_on_the_queued_one(self):
        plan = QML.plan_lane(
            [self.a(), pr(2, waiting=True, parent="0634_a"), pr(3, waiting=True)]
        )
        self.assertEqual(plan.lane, (1,))
        self.assertEqual(plan.promote, 2)
        self.assertFalse(plan.rechain)

    def test_stacked_pr_waits_until_the_first_is_really_in_the_queue(self):
        # Zielony drugi wyprzedziłby pierwszego: grupa „main + drugi” bez rodzica.
        first = pr(1, armed=True, tail="0634_a")
        plan = QML.plan_lane([first, pr(2, waiting=True, parent="0634_a")])
        self.assertEqual(plan.lane, (1,))
        self.assertIsNone(plan.promote)
        self.assertFalse(plan.rechain, "Jest już przepięty.")

    def test_armed_stacked_pr_is_parked_while_the_first_is_not_queued(self):
        first = pr(1, armed=True, tail="0634_a")
        plan = QML.plan_lane([first, pr(2, armed=True, parent="0634_a")])
        self.assertEqual(plan.lane, (1,))
        self.assertEqual(plan.park, (2,))

    def test_both_queued_in_chain_stay_and_the_third_leaves(self):
        plan = QML.plan_lane(
            [
                self.a(),
                pr(2, queue=2, armed=True, parent="0634_a", tail="0635_b"),
                pr(3, queue=3, armed=True, parent="0635_b"),
            ]
        )
        self.assertEqual(plan.lane, (1, 2))
        self.assertEqual(plan.dequeue, (3,))
        self.assertIsNone(plan.promote)

    def test_manual_add_on_the_same_parent_is_dequeued(self):
        # 02.11.2026, 19:00: #2908 i #2916 dodane ręcznie, oba na głowie maina.
        plan = QML.plan_lane(
            [
                pr(1, queue=1, armed=True, parent="0633_m", tail="0634_a"),
                pr(2, queue=2, armed=True, parent="0633_m", tail="0634_b"),
            ]
        )
        self.assertEqual(plan.lane, (1,))
        self.assertEqual(plan.dequeue, (2,))

    def test_red_waiting_pr_gets_no_second_slot_and_no_rechain_loop(self):
        plan = QML.plan_lane([self.a(), pr(2, waiting=True, healthy=False)])
        self.assertIsNone(plan.promote)
        self.assertFalse(plan.rechain)

    def test_free_second_slot_without_a_stacked_pr_asks_for_rechain(self):
        plan = QML.plan_lane([self.a(), pr(2, waiting=True, parent="0633_m")])
        self.assertIsNone(plan.promote)
        self.assertTrue(plan.rechain)

    def test_first_merged_second_is_fresh_and_keeps_the_lane(self):
        plan = QML.plan_lane([pr(2, queue=1, armed=True, parent="0634_a")])
        self.assertEqual(plan.lane, (2,))
        self.assertEqual(plan.dequeue, ())

    def test_first_dropped_second_leaves_the_queue_and_asks_for_rechain(self):
        plan = QML.plan_lane(
            [pr(2, queue=1, armed=True, parent="0634_a", fresh=False, orphan=True)]
        )
        self.assertEqual(plan.lane, ())
        self.assertEqual(plan.dequeue, (2,))
        self.assertEqual(plan.park, (2,))
        self.assertIsNone(plan.active)
        self.assertTrue(plan.rechain)

    def test_orphan_waiting_on_the_lane_member_is_not_lost(self):
        plan = QML.plan_lane(
            [self.a(), pr(2, waiting=True, parent="0634_a", fresh=False, orphan=True)]
        )
        self.assertFalse(plan.rechain)
        self.assertEqual(plan.promote, 2)

    def test_orphan_waiting_with_empty_lane_is_not_promoted(self):
        plan = QML.plan_lane(
            [pr(2, waiting=True, parent="0634_a", fresh=False, orphan=True)]
        )
        self.assertIsNone(plan.promote)
        self.assertTrue(plan.rechain)

    def test_depth_one_is_the_old_single_pr_lane(self):
        plan = QML.plan_lane([self.a(), pr(2, waiting=True, parent="0634_a")], depth=1)
        self.assertEqual(plan.lane, (1,))
        self.assertIsNone(plan.promote)
        self.assertFalse(plan.rechain)

    def test_stack_order_is_lane_then_green_waiting(self):
        self.assertEqual(
            QML.stack_order(
                [
                    pr(5, waiting=True),
                    self.a(),
                    pr(3, waiting=True, healthy=False),
                    pr(4),
                ]
            ),
            [1, 5],
        )

    def test_chain_ends_reads_annotated_headers_and_chains(self):
        self.assertEqual(
            QML.chain_ends([source("0634_a", "0633_m")]), ("0633_m", "0634_a")
        )
        self.assertEqual(
            QML.chain_ends([source("0635_b", "0634_a"), source("0634_a", "0633_m")]),
            ("0633_m", "0635_b"),
        )
        self.assertEqual(QML.chain_ends(['"""bez nagłówka"""']), (None, None))

    def test_fetch_marks_fresh_and_orphan_from_main(self):
        path = "backend/alembic/versions/"
        fake = FakeGh(
            [
                [
                    node(1, files=(path + "0634_a.py",), queue=1),
                    node(2, files=(path + "0635_b.py",), labels=("czeka-na-migracje",)),
                    node(3, files=(path + "0635_c.py",)),
                ]
            ],
            main_files="0632_x.py\n0633_m.py\n",
            blobs={
                "0633_m.py": source("0633_m", "0632_x"),
                "0634_a.py": source("0634_a", "0633_m"),
                "0635_b.py": source("0635_b", "0634_a"),
                "0635_c.py": source("0635_c", "0632_x"),
            },
        )
        prs = {p.number: p for p in quiet(QML.fetch_prs, "o/r", fake)}
        self.assertTrue(prs[1].fresh)
        self.assertFalse(prs[1].orphan)
        self.assertEqual(prs[1].tail, "0634_a")
        self.assertFalse(prs[2].fresh)
        self.assertTrue(prs[2].orphan)
        self.assertFalse(prs[3].fresh, "Numer wyższy, ale rodzic stary.")
        self.assertFalse(prs[3].orphan)
        self.assertEqual(QML.plan_lane(list(prs.values())).promote, 2)

    def test_unreadable_pr_files_do_not_stack(self):
        class NoBlobs(FakeGh):
            def __call__(self, *args, stdin=None):
                if "Accept: application/vnd.github.raw" in args and "sha2" in args[1]:
                    raise RuntimeError("boom")
                return super().__call__(*args, stdin=stdin)

        fake = NoBlobs([[node(1, queue=1), node(2, labels=("czeka-na-migracje",))]])
        prs = {p.number: p for p in quiet(QML.fetch_prs, "o/r", fake)}
        self.assertIsNone(prs[2].parent)
        self.assertIsNone(QML.plan_lane(list(prs.values())).promote)

    def test_enforce_writes_rechain_output_only_for_real_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(out)}):
                path = "backend/alembic/versions/0634_b.py"
                nodes = [node(2, files=(path,), labels=("czeka-na-migracje",))]
                blobs = {
                    "0633_m.py": source("0633_m", "0632_x"),
                    "0634_b.py": source("0634_b", "0632_x"),
                }
                fake = FakeGh([nodes], main_files="0633_m.py\n", blobs=blobs)
                quiet(QML.enforce, "o/r", dry_run=True, run=fake)
                self.assertFalse(out.exists())
                fake = FakeGh([nodes], main_files="0633_m.py\n", blobs=blobs)
                quiet(QML.enforce, "o/r", dry_run=False, run=fake)
                self.assertEqual(out.read_text(), "rechain=true\n")


class AdmitTest(unittest.TestCase):
    def test_pr_without_migration_always_enters(self):
        self.assertIsNone(QML.admit([pr(1, queue=1, armed=True)], 99))

    def test_free_lane_lets_the_pr_in(self):
        self.assertIsNone(QML.admit([pr(1, armed=True), pr(2, waiting=True)], 1))

    def test_busy_lane_names_the_active_pr(self):
        self.assertEqual(QML.admit([pr(1, queue=1, armed=True), pr(2)], 2), 1)
        self.assertEqual(QML.admit([pr(1, armed=True), pr(2)], 2), 1)

    def test_stacked_pr_enters_behind_the_queued_first(self):
        first = pr(1, queue=1, armed=True, tail="0634_a")
        self.assertIsNone(QML.admit([first, pr(2, parent="0634_a")], 2))

    def test_stacked_pr_waits_when_the_first_is_not_queued_yet(self):
        first = pr(1, armed=True, tail="0634_a")
        self.assertEqual(QML.admit([first, pr(2, parent="0634_a")], 2), 1)

    def test_third_pr_waits_behind_a_full_lane(self):
        lane = [
            pr(1, queue=1, armed=True, tail="0634_a"),
            pr(2, queue=2, armed=True, parent="0634_a", tail="0635_b"),
        ]
        self.assertEqual(QML.admit([*lane, pr(3, parent="0635_b")], 3), 1)


class ActionsTest(unittest.TestCase):
    def test_enforce_dequeues_disarms_comments_and_labels_last(self):
        fake = FakeGh(
            [[node(1, queue=1, armed=True)], [node(2, queue=2, armed=True), node(3)]]
        )
        plan = quiet(QML.enforce, "o/r", dry_run=False, run=fake)
        self.assertEqual(plan.active, 1)
        cursors = [c for c in fake.calls if "cursor=c1" in c]
        self.assertEqual(len(cursors), 1, "Druga strona PR-ów z kursorem.")
        steps = [
            c
            for c in fake.mutations()
            if any(a in ("2", "id=PR_2") or "/issues/2/" in a for a in c)
        ]
        kinds = [
            "dequeue"
            if "id=PR_2" in c
            else "disarm"
            if "--disable-auto" in c
            else "comment"
            if any("comments" in a for a in c)
            else "label"
            if "labels[]=czeka-na-migracje" in c
            else c[0]
            for c in steps
        ]
        self.assertEqual(kinds, ["dequeue", "disarm", "comment", "comment", "label"])
        self.assertEqual(sum(1 for c in fake.calls if c[:2] == ("label", "create")), 1)
        self.assertFalse(any("--squash" in c for c in fake.calls))

    def test_enforce_promotes_the_next_waiting_pr(self):
        fake = FakeGh([[node(5, labels=("czeka-na-migracje",)), node(6)]])
        plan = quiet(QML.enforce, "o/r", dry_run=False, run=fake)
        self.assertEqual(plan.promote, 5)
        self.assertIn(
            ("api", "-X", "DELETE", "repos/o/r/issues/5/labels/czeka-na-migracje"),
            fake.calls,
        )
        self.assertIn(
            ("pr", "merge", "5", "--repo", "o/r", "--squash", "--auto"), fake.calls
        )

    def test_enforce_reads_main_and_does_not_promote_a_stale_pr(self):
        fake = FakeGh(
            [
                [
                    node(
                        5,
                        labels=("czeka-na-migracje",),
                        files=("backend/alembic/versions/0631_x.py",),
                    )
                ]
            ],
            main_files="0630_a.py\n0631_b.py\nREADME\n",
        )
        plan = quiet(QML.enforce, "o/r", dry_run=False, run=fake)
        self.assertIsNone(plan.promote)
        self.assertEqual(fake.mutations(), [])

    def test_main_listing_failure_falls_back_to_old_behaviour(self):
        class NoListing(FakeGh):
            def __call__(self, *args, stdin=None):
                if "contents/backend/alembic/versions" in args[1]:
                    raise RuntimeError("boom")
                return super().__call__(*args, stdin=stdin)

        fake = NoListing([[node(5, labels=("czeka-na-migracje",))]])
        self.assertEqual(quiet(QML.enforce, "o/r", dry_run=False, run=fake).promote, 5)

    def test_admit_parks_when_the_lane_is_busy(self):
        fake = FakeGh([[node(1, queue=1, armed=True), node(2, armed=True)]])
        code = quiet(QML.admit_pr, "o/r", 2, dry_run=False, run=fake)
        self.assertEqual(code, QML.WAIT_EXIT)
        self.assertIn(
            ("pr", "merge", "2", "--repo", "o/r", "--disable-auto"), fake.calls
        )
        self.assertIn(
            (
                "api",
                "-X",
                "POST",
                "repos/o/r/issues/2/labels",
                "-f",
                "labels[]=czeka-na-migracje",
            ),
            fake.calls,
        )
        self.assertFalse(any("query=mutation" in " ".join(c) for c in fake.calls))

    def test_admit_unlabels_a_waiting_pr_when_the_lane_is_free(self):
        fake = FakeGh([[node(3, labels=("czeka-na-migracje",))]])
        self.assertEqual(quiet(QML.admit_pr, "o/r", 3, dry_run=False, run=fake), 0)
        self.assertIn(
            ("api", "-X", "DELETE", "repos/o/r/issues/3/labels/czeka-na-migracje"),
            fake.calls,
        )

    def test_dry_run_changes_nothing(self):
        fake = FakeGh([[node(1, queue=1, armed=True), node(2, queue=2, armed=True)]])
        quiet(QML.enforce, "o/r", dry_run=True, run=fake)
        self.assertEqual(fake.mutations(), [])

    def test_one_failed_step_does_not_stop_the_rest(self):
        class Failing(FakeGh):
            def __call__(self, *args, stdin=None):
                if "--disable-auto" in args:
                    self.calls.append(args)
                    raise RuntimeError("boom")
                return super().__call__(*args, stdin=stdin)

        fake = Failing([[node(1, queue=1, armed=True), node(2, queue=2, armed=True)]])
        out = io.StringIO()
        with redirect_stdout(out):
            QML.enforce("o/r", dry_run=False, run=fake)
        self.assertIn("::warning::", out.getvalue())
        self.assertTrue(any("labels[]=czeka-na-migracje" in c for c in fake.calls))


if __name__ == "__main__":
    unittest.main()
