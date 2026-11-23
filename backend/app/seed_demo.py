"""Demo seed: two insurance tenants with departments, users, collections and
sample documents, ingested through the real pipeline.  Idempotent per tenant code.
All passwords come from the DEMO_PASSWORD environment variable."""
from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import text

from app.database.session import SecurityContext, scoped_session
from app.rag.ingestion.pipeline import run_job
from app.services import document_service, identity_service, tenant_service

PLATFORM = SecurityContext(access_mode="platform", platform_role="platform_super_admin")

MOTOR_WORDING = """# ABC Motor Comprehensive Policy Wording
Policy number: POL-2026-000123. Effective date: 01/01/2026. Expiry date: 31/12/2026.

## Section 1 - Definitions
1.1 Vehicle means the motor vehicle described in the schedule, including its standard accessories.
1.2 Excess means the first amount of each claim that you must pay yourself.

## Section 2 - What is covered
2.1 We will pay for accidental loss of or damage to your vehicle, including damage caused by fire, theft and flood.
2.2 Third party liability is covered up to the limit shown in the schedule.

## Section 4 - Exclusions
4.1 We will not pay for damage caused while the vehicle is driven by an unlicensed driver.
4.2 We will not pay for mechanical or electrical breakdown or wear and tear.
4.3 We will not pay for loss when the vehicle is used for racing or speed testing.

## Section 5 - Excess
5.1 A standard excess of INR 2,500 applies to every own damage claim. A deductible of 5% applies to flood claims.
"""

CLAIMS_MANUAL = """# ABC Claims Handling Manual - Motor
## Section 3 - First notice of loss
3.1 The claims adjuster must register the first notice of loss within 24 hours and obtain the claim number.
3.2 Request the driving licence, registration certificate, FIR for theft, and photographs of the damage.
## Section 6 - Authority limits
6.1 Claims adjusters may settle own damage claims up to INR 200,000. Claims above this amount must be referred to the claims manager.
"""

HEALTH_WORDING = """# XYZ Family Health Shield Policy Wording
Policy number: POL-2026-777001. Effective date: 01/04/2026.
## Section 2 - Hospitalisation cover
2.1 We will pay reasonable medical expenses for in-patient hospitalisation of more than 24 hours.
2.2 Cashless treatment is available at network hospitals subject to pre-authorisation.
## Section 3 - Waiting periods
3.1 A waiting period of 30 days applies to all illnesses except accidents.
3.2 A waiting period of 24 months applies to pre-existing diseases.
## Section 4 - Exclusions
4.1 We will not pay for cosmetic surgery unless required following an accident.
## Section 5 - Co-payment
5.1 A co-payment of 10% applies to every claim for insured persons above 60 years of age.
"""

UW_GUIDE = """# XYZ Medical Underwriting Guideline
## Section 2 - Evidence requirements
2.1 Applicants aged 46 and above with sum insured above INR 1,000,000 must undergo a pre-policy medical check-up.
2.2 Refer applicants with declared diabetes to the medical officer before acceptance.
"""


def _tenant(db, code: str) -> dict | None:
    row = db.execute(text("SELECT tenant_id FROM platform.tenants WHERE code = :c"), {"c": code}).first()
    return tenant_service.get_tenant(db, row[0]) if row else None


def seed() -> Iterator[str]:
    pw = os.environ.get("DEMO_PASSWORD")
    if not pw:
        raise SystemExit("set DEMO_PASSWORD (min 12 chars, upper/lower/digit/symbol) for demo accounts")
    specs = [
        ("abc-general", "ABC General Insurance", "abc.com", "motor", [("motor-wordings", "Motor Policy Wordings", MOTOR_WORDING,
                                                                       "policy_wording"),
                                                                      ("claims-manuals", "Claims Manuals", CLAIMS_MANUAL, "claims_manual")]),
        ("xyz-health", "XYZ Health Insurance", "xyz.com", "health", [("health-wordings", "Health Policy Wordings", HEALTH_WORDING,
                                                                       "policy_wording"),
                                                                      ("uw-guidelines", "Underwriting Guidelines", UW_GUIDE,
                                                                       "underwriting_guideline")]),
    ]
    for code, name, domain, lob, collections in specs:
        with scoped_session(PLATFORM) as db:
            existing = _tenant(db, code)
            if existing:
                yield f"tenant {code} exists ({existing['tenant_id']})"
                continue
            t = tenant_service.create_tenant(db, PLATFORM, code=code, name=name, legal_entity=name, plan_code="professional",
                                             admin_email=f"admin@{domain}", admin_name=f"{name} Admin", admin_password=pw)
        tid = t["tenant_id"]
        admin_user = t["initial_admin"]
        sec = SecurityContext(access_mode="tenant_admin", tenant_id=tid, user_id=admin_user["user_id"],
                              account_id=admin_user["account_id"], principals=(admin_user["user_id"], tid),
                              lobs=("*",), jurisdictions=("*",), max_class=3)
        with scoped_session(sec) as db:
            deps = {c: identity_service.create_department(db, sec, c, n, None, None)["department_id"]
                    for c, n in (("CLAIMS", "Claims"), ("UW", "Underwriting"), ("CS", "Customer Service"))}
            grp = identity_service.create_group(db, sec, f"{lob}-staff", f"All {lob} staff")["group_id"]
            for uname, dep in (("adjuster", "CLAIMS"), ("underwriter", "UW"), ("agent", "CS")):
                identity_service.create_user(db, sec, email=f"{uname}@{domain}", display_name=uname.title(), password=pw,
                                             department_id=deps[dep], lines_of_business=[lob], jurisdictions=["*"],
                                             clearance_rank=2, role_codes=["member"], group_ids=[grp])
            colls = []
            for ccode, cname, *_ in collections:
                c = document_service.create_collection(db, sec, {"code": ccode, "name": cname, "line_of_business": lob,
                                                                 "classification": "internal",
                                                                 "access": [{"principal_type": "group", "principal_id": grp},
                                                                            {"principal_type": "user",
                                                                             "principal_id": admin_user["user_id"],
                                                                             "permission": "manage"}]})
                colls.append(c["collection_id"])
            jobs = []
            for cid, (ccode, _cname, body, dtype) in zip(colls, collections, strict=True):
                r = document_service.upload(db, sec, collection_id=cid, filename=f"{ccode}.md", data=body.encode(),
                                            metadata={"document_type": dtype, "insurance_line": lob}, admin=True)
                jobs.append(r["job_id"])
        for j in jobs:
            run_job(tid, j)
        yield f"tenant {code} created ({tid}); admin@{domain}, adjuster@{domain}, underwriter@{domain}, agent@{domain}"
