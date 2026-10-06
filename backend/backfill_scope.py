"""Keep the oldest requested start date when a historical backfill resumes."""
from datetime import date, timedelta
from .db import Record, encode, now


def scope_start(s, years=10, today=None):
    if type(years) is not int or years <= 0:
        raise ValueError('回補年數必須為正整數')
    calculated = ((today or date.today()) - timedelta(days=365 * years + 3)).isoformat()
    saved = s.query(Record.date).filter_by(kind='backfill_scope_start', key=str(years)).order_by(Record.date).first()
    if saved:
        # Invalid stored scope must not silently become a shorter successful run.
        original = date.fromisoformat(saved[0]).isoformat()
        return min(calculated, original)
    return calculated


def pin_scope(s, years=10, today=None):
    start = scope_start(s, years, today)
    identity = ('backfill_scope_start', str(years), start)
    if not s.get(Record, identity):
        if s.get_bind().dialect.name == 'sqlite':
            from sqlalchemy.dialects.sqlite import insert
        else:
            from sqlalchemy.dialects.postgresql import insert
        statement = insert(Record).values(kind=identity[0], key=identity[1], date=start,
            payload=encode({'years': years, 'start': start, 'created_at': now()}))
        # Immutable dated records retain the earliest scope, including simultaneous starts.
        s.execute(statement.on_conflict_do_nothing(index_elements=['kind', 'key', 'date']))
    return start
