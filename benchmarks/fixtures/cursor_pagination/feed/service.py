from .cursor import decode, encode

def list_events(events: list[dict], limit: int, cursor: str | None = None) -> dict:
    ordered = sorted(events, key=lambda e: e['created_at'])
    if cursor:
        timestamp, _ = decode(cursor)
        ordered = [e for e in ordered if e['created_at'] > timestamp]
    page = ordered[:limit]
    return {'items': page, 'next_cursor': encode(page[-1]['created_at'], page[-1]['id']) if len(page) == limit else None}
