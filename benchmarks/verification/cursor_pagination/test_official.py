import importlib, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1] / 'candidate'; sys.path.insert(0, str(ROOT))
service = importlib.import_module('feed.service')

def test_duplicate_timestamps_across_pages():
    events = [{'id': i, 'created_at': 10 if i < 4 else 11} for i in [3, 1, 5, 2, 4]]
    seen=[]; cursor=None
    while True:
        page=service.list_events(events, 2, cursor); seen += [x['id'] for x in page['items']]
        cursor=page['next_cursor']
        if cursor is None: break
    assert seen == [1,2,3,4,5]

def test_limit_contract():
    import pytest
    for value in (0, 101):
        with pytest.raises(ValueError): service.list_events([], value)
