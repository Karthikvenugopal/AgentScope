from delivery.retry import deliver_with_retry
def test_success(): assert deliver_with_retry(lambda:'ok',lambda _:None)=='ok'
