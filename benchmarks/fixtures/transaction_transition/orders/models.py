from dataclasses import dataclass
@dataclass
class Order: id: int; state: str = 'pending'
