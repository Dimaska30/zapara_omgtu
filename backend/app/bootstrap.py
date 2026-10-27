"""Create the initial administrator and print a one-time activation token."""
import argparse
from uuid import uuid4

from sqlalchemy import text

from app.auth import issue_account_token
from app.database import get_engine


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--department", required=True)
    parser.add_argument("--chair-oid", required=True)
    args = parser.parse_args()
    if not args.chair_oid.isdecimal() or len(args.chair_oid) > 20:
        parser.error("chair-oid must be a numeric source identifier")
    email = args.email.strip().lower()
    if not email or "@" not in email or not args.name.strip() or not args.department.strip():
        parser.error("valid email, name and department are required")
    user_id, department_id = uuid4(), uuid4()
    with get_engine().begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtext('zapara.bootstrap'))"))
        if connection.execute(text("SELECT EXISTS (SELECT 1 FROM zapara.system_admins WHERE revoked_at IS NULL)")).scalar_one():
            raise SystemExit("An administrator already exists")
        connection.execute(text("INSERT INTO zapara.users(id,email,display_name) VALUES (:id,:email,:name)"), {"id": user_id, "email": email, "name": args.name.strip()})
        connection.execute(text("INSERT INTO zapara.departments(id,name,source_chair_oid) VALUES (:id,:name,:oid)"), {"id": department_id, "name": args.department.strip(), "oid": args.chair_oid})
        connection.execute(text("INSERT INTO zapara.system_admins(user_id) VALUES (:id)"), {"id": user_id})
        connection.execute(text("INSERT INTO zapara.memberships(id,user_id,department_id,role) VALUES (:id,:user,:department,'admin')"), {"id": uuid4(), "user": user_id, "department": department_id})
        token = issue_account_token(connection, user_id, "invitation")
        connection.execute(text("INSERT INTO zapara.account_audit(target_id,department_id,action) VALUES (:user,:department,'bootstrap')"), {"user": user_id, "department": department_id})
    print("Одноразовый токен активации (действителен 24 часа):", token)


if __name__ == "__main__":
    main()
