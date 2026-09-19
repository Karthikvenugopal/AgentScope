from dataclasses import dataclass
@dataclass(frozen=True)
class User: id:int; organization_id:int; role:str='member'
@dataclass(frozen=True)
class Document: owner_id:int; organization_id:int; project_id:int|None=None
