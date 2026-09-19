import base64

def encode(ts: int, event_id: int) -> str:
    return base64.urlsafe_b64encode(f'{ts}:{event_id}'.encode()).decode()

def decode(value: str) -> tuple[int, int]:
    ts, event_id = base64.urlsafe_b64decode(value.encode()).decode().split(':')
    return int(ts), int(event_id)
