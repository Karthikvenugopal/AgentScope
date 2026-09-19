from feed.service import list_events

def test_first_page():
    result = list_events([{'id': 2, 'created_at': 2}, {'id': 1, 'created_at': 1}], 1)
    assert [x['id'] for x in result['items']] == [1]
    assert result['next_cursor']
