from streaming.client import stream_rows
class R(list):
    def close(self): self.closed=True
def test_rows(): assert list(stream_rows(lambda:R(['1','2'])))==[1,2]
