from datetime import date
from sqlalchemy import text


def lock_resource(connection, kind: str, external_id: str, day: date) -> None:
    key = f'zapara:resource:{kind}:{external_id}:{day.isoformat()}'
    connection.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'), {'key': key})
