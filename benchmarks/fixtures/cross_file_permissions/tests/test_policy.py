from auth.models import *
from auth.policy import can_edit
def test_owner(): assert can_edit(User(1,2),Document(1,2),{})
