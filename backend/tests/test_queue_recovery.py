"""Focused handler tests. No provider, production database, email, or UI calls.

Run with the application's Python: python -m unittest discover -s backend/tests -p test_queue_recovery.py -v
The Mongo double yields around atomic operations, so stale snapshots/races are exercised.
"""
import asyncio
import copy
from datetime import datetime, timezone
import hashlib
import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
import uuid


class DuplicateKeyError(Exception):
    pass


def matches(row, query):
    for key, wanted in query.items():
        if key == "$or":
            if not any(matches(row, branch) for branch in wanted):
                return False
            continue
        value = row.get(key)
        if isinstance(wanted, dict):
            for op, arg in wanted.items():
                if op == "$in" and value not in arg: return False
                if op == "$ne" and value == arg: return False
                if op == "$lt" and not (value is not None and value < arg): return False
                if op == "$lte" and not (value is not None and value <= arg): return False
        elif value != wanted:
            return False
    return True


class Cursor:
    def __init__(self, rows): self.rows = rows
    def sort(self, keys, direction=None):
        keys = [(keys, direction)] if isinstance(keys, str) else keys
        for key, order in reversed(keys):
            self.rows.sort(key=lambda x: x.get(key, ""), reverse=order == -1)
        return self
    def __aiter__(self): return self
    async def __anext__(self):
        await asyncio.sleep(0)
        if not self.rows: raise StopAsyncIteration
        return self.rows.pop(0)
    async def to_list(self, limit): return self.rows[:limit]


class Collection:
    def __init__(self, name):
        self.name, self.rows, self.lock = name, [], asyncio.Lock()
    def find(self, query, projection=None):
        return Cursor([copy.deepcopy(x) for x in self.rows if matches(x, query)])
    def check_unique(self, doc, original=None):
        for row in self.rows:
            if row is original:
                continue
            if doc.get("_id") is not None and row.get("_id") == doc["_id"]:
                raise DuplicateKeyError()
            if doc.get("uuid") and row.get("uuid") == doc["uuid"]:
                raise DuplicateKeyError()
            if self.name == "jobs" and (row["stage"], row["target_id"]) == (doc["stage"], doc["target_id"]):
                raise DuplicateKeyError()
            if self.name == "processing_policies":
                if (row["workspace_id"], row["version"]) == (doc["workspace_id"], doc["version"]):
                    raise DuplicateKeyError()
                if doc.get("current") and row.get("current") and row["workspace_id"] == doc["workspace_id"]:
                    raise DuplicateKeyError()
    async def find_one(self, query, projection=None, **kwargs):
        await asyncio.sleep(0)
        return next((copy.deepcopy(x) for x in self.rows if matches(x, query)), None)
    async def insert_one(self, doc):
        await asyncio.sleep(0)
        async with self.lock:
            self.check_unique(doc)
            self.rows.append(copy.deepcopy(doc))
    async def find_one_and_update(self, query, update, return_document=False, sort=None, **kwargs):
        await asyncio.sleep(0)
        async with self.lock:
            rows = [x for x in self.rows if matches(x, query)]
            if sort:
                rows.sort(key=lambda x: tuple(x.get(k, "") for k, _ in sort))
            if not rows and not kwargs.get("upsert"):
                return None
            original = rows[0] if rows else None
            old = copy.deepcopy(original)
            row = copy.deepcopy(original) if original is not None else {
                key: value for key, value in query.items() if not key.startswith("$") and not isinstance(value, dict)}
            if original is None:
                row.update(copy.deepcopy(update.get("$setOnInsert", {})))
            row.update(copy.deepcopy(update.get("$set", {})))
            for key, value in update.get("$inc", {}).items(): row[key] = row.get(key, 0) + value
            for key, value in update.get("$push", {}).items(): row.setdefault(key, []).append(copy.deepcopy(value))
            for key, value in update.get("$pull", {}).items():
                row[key] = [item for item in row.get(key, []) if not matches(item, value)]
            self.check_unique(row, original)
            if original is None:
                self.rows.append(row)
            else:
                original.clear()
                original.update(row)
            return copy.deepcopy(row if return_document else old)
    async def update_one(self, query, update, **kwargs):
        old = await self.find_one_and_update(query, update, **kwargs)
        return types.SimpleNamespace(modified_count=int(old is not None))


class Database:
    def __init__(self): self.collections = {}
    def __getattr__(self, name): return self.collections.setdefault(name, Collection(name))


class HTTPException(Exception):
    def __init__(self, status_code, detail):
        self.status_code, self.detail = status_code, detail
        super().__init__(str(detail))


class Router:
    def __init__(self, *args, **kwargs): pass
    def __getattr__(self, name):
        return lambda *args, **kwargs: lambda fn: fn


class QueueRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().slow_callback_duration = 5.0
        self.db = Database()
        self.events = []
        core = types.ModuleType("core")
        core.db = self.db
        core.now = lambda: datetime.now(timezone.utc)
        core.iso = lambda value=None: (value or core.now()).isoformat()
        core.new_id = lambda: str(uuid.uuid4())
        core.sha256_hex = lambda value: hashlib.sha256(value).hexdigest()
        core.clean = lambda value: value
        core.clean_all = lambda values: values
        core.require_role = lambda *roles: lambda: None
        core.current_user = lambda: None
        core.visit_scope = lambda user: {"workspace_id": user["workspace_id"]}
        core.assert_editable = lambda *args: None
        core.revision_conflict = lambda *args: None
        async def audit(*args): self.events.append(args)
        core.audit = audit
        async def get_visit(user, vid):
            visit = await self.db.visits.find_one({"uuid": vid, "workspace_id": user["workspace_id"]})
            if not visit: raise HTTPException(404, "Not found")
            return visit
        async def get_scoped(collection, user, uid):
            value = await getattr(self.db, collection).find_one({"uuid": uid, "workspace_id": user["workspace_id"]})
            if not value: raise HTTPException(404, "Not found")
            return value, await get_visit(user, value["visit_id"])
        core.get_visit, core.get_scoped = get_visit, get_scoped
        fastapi = types.ModuleType("fastapi")
        fastapi.APIRouter, fastapi.Depends, fastapi.HTTPException = Router, lambda fn: None, HTTPException
        calibration = types.ModuleType("calibration")
        calibration.BUDGET_MSG = "Image-call budget reached: admin approval needed"
        errors = types.ModuleType("pymongo.errors")
        errors.DuplicateKeyError = DuplicateKeyError
        modules = {"core": core, "fastapi": fastapi, "calibration": calibration,
                   "pymongo": types.ModuleType("pymongo"), "pymongo.errors": errors}
        modules.update({name: types.ModuleType(name) for name in ("storage", "ai_image", "ai_local", "ai_jev", "readiness")})
        self.patched = patch.dict(sys.modules, modules)
        self.patched.start()
        self.addCleanup(self.patched.stop)
        path = str(Path(__file__).resolve().parents[1])
        self.path_patch = patch.object(sys, "path", [path] + sys.path)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        for name in ("policy", "jobs", "routes_phase5", "routes_ai"):
            sys.modules.pop(name, None)
        self.policy = importlib.import_module("policy")
        self.jobs = importlib.import_module("jobs")
        self.routes = importlib.import_module("routes_phase5")
        self.ai = importlib.import_module("routes_ai")
        self.admin = {"uuid": "admin", "workspace_id": "ws", "role": "admin"}
        self.visit = {"uuid": "v", "workspace_id": "ws", "site_id": "site", "customer_id": "customer",
                      "processing_permission": "Policy", "status": "Draft"}
        await self.db.visits.insert_one(self.visit)
        await self.db.sites.insert_one({"uuid": "site", "workspace_id": "ws"})
        await self.db.customers.insert_one({"uuid": "customer", "workspace_id": "ws"})
        for eid in ("a", "b"):
            await self.db.evidence.insert_one({"uuid": eid, "workspace_id": "ws", "visit_id": "v"})
        await self.db.processing_policies.insert_one({"uuid": "p1", "workspace_id": "ws", "current": True,
            "version": 1, "default": "restrict", "restrictions": [], "evidence_exceptions": []})
        await self.db.cal_budget.insert_one({"_id": "hosted_image_calls", "cap": 10, "used": 1})

    async def add_job(self, uid, evidence="a", **extra):
        job = {"uuid": uid, "workspace_id": "ws", "visit_id": "v", "target_id": evidence,
               "stage": "image_analysis", "source_kind": "photo", "status": "Blocked",
               "blocker": self.jobs.BLOCKER, "revision": 1, "attempts": 0,
               "lease_owner": None, "lease_token": None, "lease_until": None, "created_at": uid, **extra}
        await self.db.jobs.insert_one(job)
        return job

    def body(self, version=1, default="restrict", exceptions=(), restrictions=()):
        return self.routes.PolicyIn(expected_version=version, default=default,
            evidence_exceptions=[{"evidence_id": key, "allow": allow} for key, allow in exceptions],
            restrictions=list(restrictions))

    async def saved(self, uid): return await self.db.jobs.find_one({"uuid": uid})

    async def test_policy_handler_resumes_only_exception_photo_and_its_run(self):
        await self.add_job("a-job")
        await self.add_job("b-job", "b")
        await self.db.image_analysis_runs.insert_one({"uuid": "run-a", "workspace_id": "ws", "visit_id": "v", "evidence_id": "a"})
        await self.add_job("run-job", "run-a", stage="photo_analysis", source_kind="photo_run")
        await self.routes.put_policy(self.body(exceptions=[("a", True)]), self.admin)
        self.assertEqual((await self.saved("a-job"))["status"], "Queued")
        self.assertEqual((await self.saved("run-job"))["status"], "Queued")
        self.assertEqual((await self.saved("b-job"))["status"], "Blocked")
        self.assertEqual(len(self.db.jobs.rows), 3)

    async def test_policy_handler_preserves_budget_other_holds_done_and_leases(self):
        original = []
        for uid, extra in [("budget", {"blocker": sys.modules["calibration"].BUDGET_MSG}),
                           ("other", {"blocker": "Manual hold"}), ("done", {"status": "Done"}),
                           ("running", {"status": "Running", "lease_owner": "worker", "lease_token": "token", "lease_until": "2099"}),
                           ("held-lease", {"lease_owner": "worker", "lease_token": "token", "lease_until": "2099"})]:
            original.append(await self.add_job(uid, uid, **extra))
        await self.routes.put_policy(self.body(default="allow"), self.admin)
        for job in original: self.assertEqual(await self.saved(job["uuid"]), job)

    async def test_permission_callback_reloads_visit_and_preserves_legacy_denial(self):
        await self.add_job("j")
        self.db.processing_policies.rows[0]["default"] = "allow"
        self.db.visits.rows[0]["processing_permission"] = "Denied"
        await self.jobs.on_permission_change(self.visit)
        self.assertEqual((await self.saved("j"))["status"], "Blocked")
        self.db.visits.rows[0]["processing_permission"] = "Granted"
        await self.jobs.on_permission_change(self.visit)
        self.assertEqual((await self.saved("j"))["status"], "Queued")

    async def test_site_customer_and_visit_restrictions_remain_effective(self):
        await self.add_job("j", status="Queued", blocker=None)
        for version, (scope, key) in enumerate([("site", "site"), ("customer", "customer"), ("visit", "v")], 1):
            await self.routes.put_policy(self.body(version, default="allow", restrictions=[{"scope": scope, "id": key}]), self.admin)
            self.assertFalse((await self.policy.evaluate_job(await self.saved("j")))["allowed"])
            self.assertEqual((await self.saved("j"))["status"], "Blocked")

    async def test_false_exception_blocks_queue_and_transcript_maps_to_evidence(self):
        await self.add_job("a-job", status="Queued", blocker=None)
        await self.db.transcripts.insert_one({"uuid": "transcript", "workspace_id": "ws", "visit_id": "v", "evidence_id": "a"})
        await self.add_job("text-job", "transcript", stage="text_checks", source_kind="transcript", status="Queued", blocker=None)
        await self.routes.put_policy(self.body(default="allow", exceptions=[("a", False)]), self.admin)
        self.assertEqual((await self.saved("a-job"))["status"], "Blocked")
        self.assertEqual((await self.saved("text-job"))["status"], "Blocked")

    async def test_workspace_and_missing_or_foreign_sources_fail_closed(self):
        foreign = await self.add_job("foreign", workspace_id="other")
        missing = await self.add_job("missing", "missing")
        await self.db.image_analysis_runs.insert_one({"uuid": "bad-run", "workspace_id": "ws", "visit_id": "v", "evidence_id": "foreign-evidence"})
        await self.db.evidence.insert_one({"uuid": "foreign-evidence", "workspace_id": "other", "visit_id": "v"})
        await self.add_job("bad-run-job", "bad-run", stage="photo_analysis", source_kind="photo_run")
        await self.routes.put_policy(self.body(default="allow"), self.admin)
        self.assertEqual(await self.saved("foreign"), foreign)
        self.assertEqual((await self.saved("missing"))["status"], "Blocked")
        self.assertEqual((await self.saved("bad-run-job"))["status"], "Blocked")
        with self.assertRaises(HTTPException) as caught:
            await self.ai.retry_job("foreign", self.admin)
        self.assertEqual(caught.exception.status_code, 404)

    async def test_retry_handler_enforces_permission_and_budget_then_reuses_job(self):
        await self.add_job("j", status="Failed")
        with self.assertRaises(HTTPException): await self.ai.retry_job("j", self.admin)
        self.db.processing_policies.rows[0]["default"] = "allow"
        budget = self.db.cal_budget.rows[0]
        budget["used"] = budget["cap"]
        before = copy.deepcopy(budget)
        with self.assertRaises(HTTPException) as caught: await self.ai.retry_job("j", self.admin)
        self.assertEqual(caught.exception.detail["code"], "budget_reached")
        self.assertEqual(budget, before)
        budget["used"] -= 1
        result = await self.ai.retry_job("j", self.admin)
        self.assertEqual((result["uuid"], result["status"]), ("j", "Queued"))
        self.assertEqual(len(self.db.jobs.rows), 1)

    async def test_policy_release_at_exhausted_budget_stays_held_without_cap_change(self):
        await self.add_job("j")
        self.db.cal_budget.rows[0]["used"] = 10
        before = copy.deepcopy(self.db.cal_budget.rows)
        await self.routes.put_policy(self.body(default="allow"), self.admin)
        result = await self.saved("j")
        self.assertEqual(result["status"], "Blocked")
        self.assertEqual(result["blocker"], sys.modules["calibration"].BUDGET_MSG)
        self.assertEqual(self.db.cal_budget.rows, before)

    async def test_concurrent_policy_updates_retry_and_claim_have_one_execution(self):
        await self.add_job("j", status="Failed")
        async def retry():
            try: return await self.ai.retry_job("j", self.admin)
            except HTTPException as exc:
                self.assertEqual(exc.status_code, 409)
        results = await asyncio.gather(self.routes.put_policy(self.body(default="allow"), self.admin),
            self.routes.put_policy(self.body(default="allow"), self.admin),
            *(retry() for _ in range(20)), return_exceptions=True)
        failures = [r for r in results[:2] if isinstance(r, HTTPException)]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].status_code, 409)
        self.assertFalse(any(isinstance(r, Exception) for r in results[2:]))
        await self.ai.retry_job("j", self.admin)
        claims = await asyncio.gather(*(self.jobs._claim("image_analysis") for _ in range(20)))
        winners = [j for j in claims if j]
        self.assertEqual(len(winners), 1)
        self.assertEqual(len(self.db.jobs.rows), 1)
        runs = []
        async def handler(job, visit):
            runs.append((job["uuid"], job["lease_token"]))
            await self.jobs._finish(job, "Done")
        self.jobs.HANDLERS["image_analysis"] = handler
        await self.jobs._execute(winners[0])
        self.assertEqual(len(runs), 1)
        self.assertEqual((await self.saved("j"))["status"], "Done")
        self.assertEqual(sum(e[2] == "processing_retry" for e in self.events), 1)

    async def test_policy_revocation_after_claim_is_rechecked_before_handler(self):
        await self.add_job("j")
        await self.routes.put_policy(self.body(default="allow"), self.admin)
        claimed = await self.jobs._claim("image_analysis")
        active = await self.saved("j")
        await self.routes.put_policy(self.body(version=2), self.admin)
        self.assertEqual(await self.saved("j"), active)
        called = []
        async def handler(*args): called.append(True)
        self.jobs.HANDLERS["image_analysis"] = handler
        await self.jobs._execute(claimed)
        self.assertFalse(called)
        self.assertEqual((await self.saved("j"))["status"], "Blocked")

    async def test_running_handler_lease_survives_policy_change_and_retries(self):
        await self.add_job("j")
        await self.routes.put_policy(self.body(default="allow"), self.admin)
        claimed = await self.jobs._claim("image_analysis")
        started, finish = asyncio.Event(), asyncio.Event()
        async def handler(job, visit):
            started.set()
            await finish.wait()
            await self.jobs._finish(job, "Done")
        self.jobs.HANDLERS["image_analysis"] = handler
        task = asyncio.create_task(self.jobs._execute(claimed))
        await started.wait()
        snapshot = await self.saved("j")
        await self.routes.put_policy(self.body(version=2), self.admin)
        await asyncio.gather(*(self.ai.retry_job("j", self.admin) for _ in range(20)))
        self.assertEqual((await self.saved("j"))["lease_token"], snapshot["lease_token"])
        self.assertEqual((await self.saved("j"))["status"], "Running")
        self.assertIsNone(await self.jobs._claim("image_analysis"))
        finish.set()
        await task

    async def test_enqueue_and_concurrent_duplicate_registration_share_one_job(self):
        self.db.processing_policies.rows[0]["evidence_exceptions"] = [{"evidence_id": "a", "allow": True}]
        jobs = await asyncio.gather(*(self.jobs.enqueue(self.visit, "image_analysis", "a", "photo") for _ in range(20)))
        self.assertEqual(len({j["uuid"] for j in jobs}), 1)
        self.assertEqual(len(self.db.jobs.rows), 1)
        self.assertTrue(all(j["status"] == "Queued" for j in jobs))

    async def test_publication_never_exposes_a_missing_current_policy(self):
        observations = []
        async def read_many():
            for _ in range(30): observations.append(await self.policy.current("ws"))
        await asyncio.gather(read_many(), self.routes.put_policy(self.body(), self.admin))
        self.assertTrue(all(p["default"] == "restrict" for p in observations))
        self.assertEqual(sum(p["current"] for p in self.db.processing_policies.rows), 1)
        self.assertEqual(sorted(p["version"] for p in self.db.processing_policies.rows), [1, 2])

    async def test_sweep_finishes_interrupted_policy_change_without_releasing_budget_hold(self):
        await self.add_job("policy")
        budget = await self.add_job("budget", "b", blocker=sys.modules["calibration"].BUDGET_MSG)
        # Simulate publication succeeding before the process crashes, before its callback.
        self.db.processing_policies.rows[0]["default"] = "allow"
        await self.jobs.recover_policy_blocked()
        self.assertEqual((await self.saved("policy"))["status"], "Queued")
        self.assertEqual(await self.saved("budget"), budget)

    async def test_archive_failure_keeps_history_and_audit_intent_then_recovers(self):
        await self.add_job("j")
        collection = self.db.processing_policies
        original = collection.update_one
        async def fail_archive(query, update, **kwargs):
            if kwargs.get("upsert"):
                raise OSError("archive unavailable")
            return await original(query, update, **kwargs)
        with patch.object(collection, "update_one", fail_archive), self.assertLogs("policy", level="ERROR"):
            result = await self.routes.put_policy(self.body(default="allow"), self.admin)
        self.assertTrue(result["history_pending"])
        current = await collection.find_one({"current": True})
        pending = current[self.policy.PENDING]
        self.assertEqual((pending[0]["previous"]["version"], pending[0]["previous"]["default"]), (1, "restrict"))
        self.assertEqual(pending[0]["audit"]["actor_id"], "admin")
        self.assertEqual([p["version"] for p in (await self.routes.policy_versions(self.admin))["versions"]], [2, 1])
        self.assertEqual((await self.saved("j"))["status"], "Queued")
        await self.policy.recover_pending()
        self.assertEqual(sorted(p["version"] for p in collection.rows), [1, 2])
        self.assertEqual(len(self.db.audit_events.rows), 1)
        self.assertEqual((await collection.find_one({"current": True}))[self.policy.PENDING], [])

    async def test_audit_failure_keeps_intent_and_recovery_is_idempotent(self):
        original = self.db.audit_events.update_one
        async def fail_audit(*args, **kwargs):
            raise OSError("audit unavailable")
        with patch.object(self.db.audit_events, "update_one", fail_audit), self.assertLogs("policy", level="ERROR"):
            result = await self.routes.put_policy(self.body(default="allow"), self.admin)
        self.assertTrue(result["history_pending"])
        self.assertEqual(sorted(p["version"] for p in self.db.processing_policies.rows), [1, 2])
        self.assertEqual(len((await self.db.processing_policies.find_one({"current": True}))[self.policy.PENDING]), 1)
        await self.policy.recover_pending()
        await self.policy.recover_pending()
        self.assertEqual(len(self.db.audit_events.rows), 1)
        event = self.db.audit_events.rows[0]
        self.assertEqual((event["actor_id"], event["action"], event["detail"]), ("admin", "policy_changed", {"version": 2}))

    async def test_failure_after_audit_before_ack_does_not_duplicate_audit(self):
        collection = self.db.processing_policies
        original = collection.update_one
        async def fail_ack(query, update, **kwargs):
            if "$pull" in update:
                raise OSError("completion acknowledgment unavailable")
            return await original(query, update, **kwargs)
        with patch.object(collection, "update_one", fail_ack), self.assertLogs("policy", level="ERROR"):
            result = await self.routes.put_policy(self.body(default="allow"), self.admin)
        self.assertTrue(result["history_pending"])
        self.assertEqual(len(self.db.audit_events.rows), 1)
        await self.policy.recover_pending()
        self.assertEqual(len(self.db.audit_events.rows), 1)
        self.assertEqual((await collection.find_one({"current": True}))[self.policy.PENDING], [])

    async def test_crash_after_publication_preserves_both_versions_and_recovers_jobs(self):
        await self.add_job("j")
        async def crash(*args):
            raise SystemExit("process interrupted after publication")
        with patch.object(self.policy, "flush_pending", crash), self.assertRaises(SystemExit):
            await self.routes.put_policy(self.body(default="allow"), self.admin)
        current = await self.db.processing_policies.find_one({"current": True})
        self.assertEqual((current["version"], current[self.policy.PENDING][0]["previous"]["version"]), (2, 1))
        self.assertEqual((await self.saved("j"))["status"], "Blocked")
        await self.policy.recover_pending()
        await self.jobs.recover_policy_blocked()
        self.assertEqual((await self.saved("j"))["status"], "Queued")
        self.assertEqual(sorted(p["version"] for p in self.db.processing_policies.rows), [1, 2])
        self.assertEqual(len(self.db.audit_events.rows), 1)

    async def test_multiple_pending_changes_survive_concurrent_recovery(self):
        async def unavailable(*args):
            raise OSError("deferred completion")
        with patch.object(self.policy, "flush_pending", unavailable), self.assertLogs("policy", level="ERROR"):
            await self.routes.put_policy(self.body(default="allow"), self.admin)
            await self.routes.put_policy(self.body(version=2), self.admin)
        current = await self.db.processing_policies.find_one({"current": True})
        self.assertEqual(len(current[self.policy.PENDING]), 2)
        self.assertTrue(all(self.policy.PENDING not in e["previous"] for e in current[self.policy.PENDING]))
        await asyncio.gather(*(self.policy.recover_pending() for _ in range(10)))
        self.assertEqual(sorted(p["version"] for p in self.db.processing_policies.rows), [1, 2, 3])
        self.assertEqual(len(self.db.audit_events.rows), 2)
        self.assertEqual(sum(p["current"] for p in self.db.processing_policies.rows), 1)
        current = await self.db.processing_policies.find_one({"current": True})
        self.assertEqual((current["default"], current[self.policy.PENDING]), ("restrict", []))

    async def test_failed_atomic_publication_leaves_existing_policy_intact(self):
        before = copy.deepcopy(self.db.processing_policies.rows)
        original = self.db.processing_policies.find_one_and_update
        async def fail_publication(query, update, **kwargs):
            if "$push" in update:
                raise OSError("publication unavailable")
            return await original(query, update, **kwargs)
        with patch.object(self.db.processing_policies, "find_one_and_update", fail_publication), self.assertRaises(OSError):
            await self.routes.put_policy(self.body(default="allow"), self.admin)
        self.assertEqual(self.db.processing_policies.rows, before)
        self.assertEqual(self.db.audit_events.rows, [])

    async def test_conflicting_history_is_preserved_and_stays_pending(self):
        async def unavailable(*args):
            raise OSError("deferred completion")
        with patch.object(self.policy, "flush_pending", unavailable), self.assertLogs("policy", level="ERROR"):
            await self.routes.put_policy(self.body(default="allow"), self.admin)
        conflicting = {"uuid": "conflict", "workspace_id": "ws", "version": 1, "current": False, "default": "allow"}
        await self.db.processing_policies.insert_one(conflicting)
        with self.assertLogs("policy", level="ERROR"):
            await self.policy.recover_pending()
        self.assertEqual(await self.db.processing_policies.find_one({"version": 1}), conflicting)
        self.assertEqual(len((await self.db.processing_policies.find_one({"current": True}))[self.policy.PENDING]), 1)
        self.assertEqual(self.db.audit_events.rows, [])


if __name__ == "__main__":
    unittest.main()
