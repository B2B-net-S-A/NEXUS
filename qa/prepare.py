"""Seed a small, private HTTP workload on the disposable CI stack only."""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("QA requests must not redirect to another service")


def stack_url() -> str:
    url = os.environ.get("E2E_API_URL", "").rstrip("/")
    if url not in {"http://localhost:8000", "http://127.0.0.1:8000"}:
        raise RuntimeError("QA supports only the disposable stack on localhost:8000")
    if os.environ.get("QA_CONFIRM") != "nexus-e2e":
        raise RuntimeError("QA_CONFIRM=nexus-e2e is required")
    return url


def main() -> None:
    base = stack_url()
    password = os.environ["E2E_USER_PASSWORD"]
    opener = build_opener(NoRedirects())

    def call(path, *, token=None, data=None, status=200, form=None):
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = None
        if data is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data).encode()
        if form is not None:
            # This endpoint takes FastAPI Form fields; no uploaded file is required.
            from urllib.parse import urlencode

            headers["Content-Type"] = "application/x-www-form-urlencoded"
            body = urlencode(form).encode()
        try:
            response = opener.open(
                Request(base + path, data=body, headers=headers), timeout=30
            )
        except HTTPError as exc:
            # Never print credentials or response bodies to CI logs.
            raise RuntimeError(
                f"{path}: expected {status}, received {exc.code}"
            ) from None
        with response:
            if response.status != status:
                raise RuntimeError(
                    f"{path}: expected {status}, received {response.status}"
                )
            return json.load(response)

    sessions = {}
    for role, email in [
        ("admin", "e2e-admin@example.com"),
        ("recruiter", "e2e-recruiter@example.com"),
    ]:
        token = call("/api/auth/login", data={"email": email, "password": password})[
            "access_token"
        ]
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print(f"::add-mask::{token}")
        sessions[role] = {"token": token, "id": call("/api/auth/me", token=token)["id"]}
    admin = sessions["admin"]["token"]
    suffix = uuid4().hex[:10]
    candidates, clients, jobs, contracts = [], [], [], []
    start, end = (
        (date.today() - timedelta(days=10)).isoformat(),
        (date.today() + timedelta(days=80)).isoformat(),
    )
    for i in range(3):
        client = call(
            "/api/clients",
            token=admin,
            status=201,
            data={"name": f"QA Load {suffix} {i}", "status": "active"},
        )
        clients.append(client["id"])
        job = call(
            "/api/jobs",
            token=admin,
            status=201,
            data={
                "title": f"QA Python {suffix} {i}",
                "client_id": client["id"],
                "recruiter_id": sessions["recruiter"]["id"],
            },
        )
        jobs.append(job["id"])
        for j in range(4):
            candidate = call(
                "/api/candidates",
                token=admin,
                status=201,
                data={
                    "name": "Ewa",
                    "lastname": f"QA{suffix}{i}{j}",
                    "email": f"qa-{suffix}-{i}-{j}@example.com",
                },
            )
            candidates.append(candidate["id"])
            call(
                "/api/pipeline/move",
                token=admin,
                data={
                    "candidate_id": candidate["id"],
                    "job_id": job["id"],
                    "stage": "screening",
                },
            )
        contract = call(
            "/api/contracts",
            token=admin,
            status=201,
            data={
                "candidate_id": candidates[-1],
                "client_id": client["id"],
                "contract_type": "b2b",
                "start_date": start,
                "rate_candidate": 120,
                "rate_unit": "hourly",
            },
        )
        contracts.append(contract["id"])
        call(
            f"/api/clients/{client['id']}/orders",
            token=admin,
            status=201,
            form={
                "contract_id": contract["id"],
                "title": f"QA-{suffix}-{i}",
                "order_type": "periodic",
                "order_status": "active",
                "start_date": start,
                "end_date": end,
                "rate_client": 160,
                "rate_unit": "hourly",
            },
        )
    result = {
        "base_url": base,
        "sessions": sessions,
        "candidates": candidates,
        "clients": clients,
        "jobs": jobs,
        "contracts": contracts,
        "search": f"QA{suffix}",
    }
    path = Path(".qa/workload.json")
    path.parent.mkdir(exist_ok=True)
    with path.open(
        "w", opener=lambda name, flags: os.open(name, flags, 0o600)
    ) as handle:
        json.dump(result, handle)
    # Separate public metadata, with neither tokens nor individual records.
    Path("qa/reports").mkdir(parents=True, exist_ok=True)
    Path("qa/reports/workload.json").write_text(
        json.dumps(
            {
                "target": "ephemeral CI stack",
                "sha": os.environ.get("GIT_SHA"),
                "candidates": len(candidates),
                "clients": len(clients),
                "jobs": len(jobs),
                "contracts": len(contracts),
                "accounts": len(sessions),
                "limitation": "Small synthetic dataset; not production capacity evidence",
            },
            indent=2,
        )
    )
    print(
        "QA workload: 12 candidates, 3 clients, 3 jobs, 3 contracts with orders; 2 accounts"
    )


if __name__ == "__main__":
    main()
