import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'candidate'))
from auth.models import User,Document
from auth.policy import can_edit
def test_rules():
    doc=Document(1,10,7); memberships={(2,7):'editor',(3,7):'viewer'}
    assert can_edit(User(1,10),doc,memberships)
    assert can_edit(User(2,10),doc,memberships)
    assert can_edit(User(9,10,'admin'),doc,memberships)
    assert not can_edit(User(3,10),doc,memberships)
    assert not can_edit(User(1,11,'admin'),doc,memberships)
