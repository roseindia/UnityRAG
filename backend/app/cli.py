"""Operator CLI.

    python -m app.cli create-platform-admin --email admin@example.com --password '...'
    python -m app.cli seed-demo            # two demo insurance tenants with documents
    python -m app.cli aggregate --days 7   # run usage aggregation now

`create-platform-admin` is the bootstrap path for the very first platform
administrator; it runs with the API database role in an explicit platform
context and is audited like every other platform action.
"""
from __future__ import annotations

import argparse
import getpass
import uuid

from sqlalchemy import text

from app.core.errors import ValidationFailed
from app.database.session import SecurityContext, scoped_session
from app.security.passwords import hash_password, password_policy_errors
from app.services.audit import platform_audit

BOOTSTRAP = SecurityContext(access_mode="platform", platform_role="platform_super_admin")


def create_platform_admin(email: str, password: str, name: str = "Platform Administrator",
                          role: str = "platform_super_admin") -> uuid.UUID:
    errs = password_policy_errors(password)
    if errs:
        raise ValidationFailed("password policy: " + "; ".join(errs))
    with scoped_session(BOOTSTRAP) as db:
        account_id = db.execute(text("SELECT account_id FROM iam.user_accounts WHERE email = :e"), {"e": email.lower()}).scalar()
        if account_id is None:
            account_id = uuid.uuid4()
            db.execute(text("INSERT INTO iam.user_accounts (account_id, email, display_name, password_hash) VALUES (:a, :e, :n, :h)"),
                       {"a": account_id, "e": email.lower(), "n": name, "h": hash_password(password)})
        role_id = db.execute(text("SELECT role_id FROM platform.platform_roles WHERE code = :c"), {"c": role}).scalar_one()
        db.execute(text("""INSERT INTO platform.platform_users (account_id, role_id) VALUES (:a, :r)
                           ON CONFLICT (account_id) DO UPDATE SET role_id = EXCLUDED.role_id, status = 'active'"""),
                   {"a": account_id, "r": role_id})
        platform_audit(db, category="administration", action="platform_admin_bootstrapped", severity="high",
                       target_type="platform_user", target_id=account_id, detail={"role": role, "via": "cli"})
    return account_id


def main() -> None:
    from app.core.logging import configure_logging

    configure_logging("INFO", "cli")
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("create-platform-admin")
    a.add_argument("--email", required=True)
    a.add_argument("--password")
    a.add_argument("--name", default="Platform Administrator")
    sub.add_parser("seed-demo")
    g = sub.add_parser("aggregate")
    g.add_argument("--days", type=int, default=1)
    args = p.parse_args()
    if args.cmd == "create-platform-admin":
        pw = args.password or getpass.getpass("Password: ")
        print("platform admin account:", create_platform_admin(args.email, pw, args.name))
    elif args.cmd == "seed-demo":
        from app.seed_demo import seed

        for line in seed():
            print(line)
    elif args.cmd == "aggregate":
        from app.analytics.aggregation import aggregate_all

        print("tenant-days aggregated:", aggregate_all(args.days))


if __name__ == "__main__":
    main()
