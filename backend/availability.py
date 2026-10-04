"""Separate a reporting period from the date data became available."""
from datetime import date


def available_on(row, kind):
    period = row.get('date', '')[:10]
    if kind not in ('fundamentals', 'financials'):
        return period or None
    dates = []
    for key in ('published_date', 'announcement_date', 'release_date', 'create_time'):
        value = str(row.get(key, ''))[:10]
        try:
            date.fromisoformat(value)
            dates.append(value)
        except ValueError:
            continue
    # No inferred announcement date from a month-start or quarter-end label.
    return max([period, *dates]) if dates else None


def known_as_of(row, kind, asof):
    published = available_on(row, kind)
    return published is not None and published <= asof
