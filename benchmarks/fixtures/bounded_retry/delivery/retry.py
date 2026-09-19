def deliver_with_retry(send, sleep, max_attempts=3, base_delay=0.1):
    return send()
