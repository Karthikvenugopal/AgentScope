from .parser import parse
def stream_rows(open_response):
    response=open_response()
    for line in response:
        yield parse(line)
