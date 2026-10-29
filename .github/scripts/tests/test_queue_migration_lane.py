import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

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


def pr(number, queue=None, armed=False, waiting=False, healthy=True):
    return QML.Pr(number, f"PR_{number}", queue, armed, waiting, healthy)


class FakeGh:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def __call__(self, *args, stdin=None):
        self.calls.append(args)
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
            if c[:2] != ("api", "graphql") or "query=mutation" in c[3]
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
        self.assertEqual(plan.park, (10, 12))
        self.assertIsNone(plan.promote)

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

    def test_active_pr_with_the_wait_label_loses_it(self):
        plan = QML.plan_lane([pr(50, queue=1, armed=True, waiting=True)])
        self.assertEqual(plan.active, 50)
        self.assertEqual(plan.unlabel, 50)

    def test_nothing_to_do(self):
        self.assertEqual(QML.plan_lane([pr(60)]), QML.Plan(active=None))
        self.assertEqual(QML.plan_lane([]), QML.Plan(active=None))


class AdmitTest(unittest.TestCase):
    def test_pr_without_migration_always_enters(self):
        self.assertIsNone(QML.admit([pr(1, queue=1, armed=True)], 99))

    def test_free_lane_lets_the_pr_in(self):
        self.assertIsNone(QML.admit([pr(1, armed=True), pr(2, waiting=True)], 1))

    def test_busy_lane_names_the_active_pr(self):
        self.assertEqual(QML.admit([pr(1, queue=1, armed=True), pr(2)], 2), 1)
        self.assertEqual(QML.admit([pr(1, armed=True), pr(2)], 2), 1)


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
