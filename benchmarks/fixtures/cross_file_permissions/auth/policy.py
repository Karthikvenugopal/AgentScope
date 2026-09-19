from .membership import project_role
def can_edit(user, document, memberships):
    return user.id == document.owner_id
