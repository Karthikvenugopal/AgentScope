from .membership import project_role
def can_edit(user, document, memberships):
    if user.organization_id != document.organization_id: return False
    if user.role == 'admin' or user.id == document.owner_id: return True
    return document.project_id is not None and project_role(memberships,user.id,document.project_id) == 'editor'
