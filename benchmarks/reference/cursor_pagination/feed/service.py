from .cursor import decode, encode

def list_events(events: list[dict], limit: int, cursor: str | None = None) -> dict:
    if limit < 1 or limit > 100:
        raise ValueError('limit must be between 1 and 100')
    ordered = sorted(events, key=lambda e: (e['created_at'], e['id']))
    if cursor:
        boundary = decode(cursor)
        ordered = [e for e in ordered if (e['created_at'], e['id']) > boundary]
    page = ordered[:limit]
    has_more = len(ordered) > limit
    return {'items': page, 'next_cursor': encode(page[-1]['created_at'], page[-1]['id']) if has_more else None}
