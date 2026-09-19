from .errors import TransientError

def deliver_with_retry(send, sleep, max_attempts=3, base_delay=0.1):
    if max_attempts < 1: raise ValueError('max_attempts must be positive')
    for attempt in range(max_attempts):
        try: return send()
        except TransientError:
            if attempt + 1 == max_attempts: raise
            sleep(base_delay * (2 ** attempt))
    raise AssertionError('unreachable')
