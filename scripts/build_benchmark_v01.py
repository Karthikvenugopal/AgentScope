"""Materialize the frozen AgentScope Benchmark v0.1 task fixtures.

The generated content is intentionally dependency-free and deterministic. Existing
task directories are never overwritten, except the Phase 3 task manifest receives
the v0.1 catalog metadata on its first migration.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS = ROOT / "benchmarks"


TASKS: dict[str, dict[str, object]] = {
    "request_validation": {
        "title": "Enforce request validation",
        "description": "Reject malformed signup payloads without changing the service API. Email must contain a local part and dotted domain; names are required and limited to 80 characters. Normalize accepted values without mutating the input.",
        "expected": "validate_signup returns normalized data or a field-specific ValidationError.",
        "difficulty": "easy",
        "version": "1.0.1",
        "language": "Python",
        "tags": ["api", "validation", "bugfix"],
        "files": {
            "README.md": "# Signup service\n\nValidation lives in `signup/validation.py`. Email and name must be strings. Email is trimmed, lowercased, and must have a local part plus a dotted domain. Name is trimmed, required, and limited to 80 characters. Validation errors name the invalid field and the input mapping must not be mutated.\n",
            "signup/__init__.py": "from .validation import ValidationError, validate_signup\n\n__all__ = ['ValidationError', 'validate_signup']\n",
            "signup/validation.py": """class ValidationError(ValueError):
    pass


def validate_signup(payload: dict[str, object]) -> dict[str, str]:
    email = str(payload.get('email', '')).strip()
    name = str(payload.get('name', '')).strip()
    return {'email': email, 'name': name}
""",
            "tests/test_validation.py": """import pytest
from signup import ValidationError, validate_signup


def test_valid_signup():
    assert validate_signup({'email': ' A@B.COM ', 'name': ' Ada '}) == {'email': 'a@b.com', 'name': 'Ada'}


def test_missing_email():
    with pytest.raises(ValidationError):
        validate_signup({'name': 'Ada'})
""",
        },
        "reference": {
            "signup/validation.py": """import re


class ValidationError(ValueError):
    pass


def validate_signup(payload: dict[str, object]) -> dict[str, str]:
    email = str(payload.get('email', '')).strip().lower()
    name = str(payload.get('name', '')).strip()
    if not email or not re.fullmatch(r'[^@\\s]+@[^@\\s]+\\.[^@\\s]+', email):
        raise ValidationError('email')
    if not name or len(name) > 80:
        raise ValidationError('name')
    return {'email': email, 'name': name}
"""
        },
        "official": """import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1] / 'candidate'
spec = importlib.util.spec_from_file_location('validation', ROOT / 'signup/validation.py')
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

@pytest.mark.parametrize('payload,field', [({}, 'email'), ({'email': 'x', 'name': 'Ada'}, 'email'), ({'email': 'a@b.co', 'name': ' '}, 'name'), ({'email': 'a@b.co', 'name': 'x'*81}, 'name')])
def test_rejects(payload, field):
    with pytest.raises(mod.ValidationError, match=field): mod.validate_signup(payload)

def test_normalizes_without_mutation():
    p = {'email': ' A@B.COM ', 'name': ' Ada '}
    assert mod.validate_signup(p) == {'email': 'a@b.com', 'name': 'Ada'}
    assert p['email'] == ' A@B.COM '
""",
    },
    "cursor_pagination": {
        "title": "Repair cursor pagination",
        "description": "Return stable, non-overlapping pages from the event store, including duplicate timestamps.",
        "expected": "Pages use an opaque (timestamp,id) cursor and never skip or duplicate events.",
        "difficulty": "medium",
        "language": "Python",
        "tags": ["api", "pagination", "data"],
        "files": {
            "README.md": "# Event feed\n\nThe public entry point is `feed.service.list_events`.\n",
            "feed/__init__.py": "",
            "feed/cursor.py": """import base64

def encode(ts: int, event_id: int) -> str:
    return base64.urlsafe_b64encode(f'{ts}:{event_id}'.encode()).decode()

def decode(value: str) -> tuple[int, int]:
    ts, event_id = base64.urlsafe_b64decode(value.encode()).decode().split(':')
    return int(ts), int(event_id)
""",
            "feed/service.py": """from .cursor import decode, encode

def list_events(events: list[dict], limit: int, cursor: str | None = None) -> dict:
    ordered = sorted(events, key=lambda e: e['created_at'])
    if cursor:
        timestamp, _ = decode(cursor)
        ordered = [e for e in ordered if e['created_at'] > timestamp]
    page = ordered[:limit]
    return {'items': page, 'next_cursor': encode(page[-1]['created_at'], page[-1]['id']) if len(page) == limit else None}
""",
            "tests/test_feed.py": """from feed.service import list_events

def test_first_page():
    result = list_events([{'id': 2, 'created_at': 2}, {'id': 1, 'created_at': 1}], 1)
    assert [x['id'] for x in result['items']] == [1]
    assert result['next_cursor']
""",
        },
        "reference": {
            "feed/service.py": """from .cursor import decode, encode

def list_events(events: list[dict], limit: int, cursor: str | None = None) -> dict:
    if limit < 1 or limit > 100:
        raise ValueError('limit must be between 1 and 100')
    ordered = sorted(events, key=lambda e: (e['created_at'], e['id']))
    if cursor:
        boundary = decode(cursor)
        ordered = [e for e in ordered if (e['created_at'], e['id']) > boundary]
    page = ordered[:limit]
    has_more = len(ordered) > limit
    return {'items': page, 'next_cursor': encode(page[-1]['created_at'], page[-1]['id']) if has_more else None}
"""
        },
        "official": """import importlib, sys
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
""",
    },
    "transaction_transition": {
        "title": "Make order transitions atomic",
        "description": "Repair an order state transition that can persist inventory changes when payment fails.",
        "expected": "Checkout commits order and inventory together or rolls both back.",
        "difficulty": "medium",
        "language": "Python",
        "tags": ["transactions", "state", "reliability"],
        "files": {
            "README.md": "# Orders\n\n`checkout` coordinates repository and payment state.\n",
            "orders/models.py": """from dataclasses import dataclass
@dataclass
class Order: id: int; state: str = 'pending'
""",
            "orders/repository.py": """class Repository:
    def __init__(self, stock=1): self.stock=stock; self.states={}
    def save(self, order): self.states[order.id]=order.state
""",
            "orders/service.py": """def checkout(order, repository, charge):
    if order.state != 'pending': raise ValueError('invalid transition')
    repository.stock -= 1
    charge(order.id)
    order.state = 'paid'
    repository.save(order)
""",
            "tests/test_checkout.py": """from orders.models import Order
from orders.repository import Repository
from orders.service import checkout

def test_success():
    r=Repository(); o=Order(1); checkout(o,r,lambda _: None)
    assert (o.state,r.stock,r.states[1]) == ('paid',0,'paid')
""",
        },
        "reference": {"orders/service.py": """def checkout(order, repository, charge):
    if order.state != 'pending': raise ValueError('invalid transition')
    if repository.stock < 1: raise ValueError('out of stock')
    old_stock, old_state = repository.stock, order.state
    try:
        charge(order.id)
        repository.stock -= 1
        order.state = 'paid'
        repository.save(order)
    except BaseException:
        repository.stock, order.state = old_stock, old_state
        repository.states.pop(order.id, None)
        raise
"""},
        "official": """import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'candidate'; sys.path.insert(0,str(ROOT))
from orders.models import Order
from orders.repository import Repository
from orders.service import checkout

def test_failure_rolls_back():
    r=Repository(); o=Order(7)
    try: checkout(o,r,lambda _: (_ for _ in ()).throw(RuntimeError('declined')))
    except RuntimeError: pass
    assert (o.state,r.stock,r.states) == ('pending',1,{})

def test_no_stock_does_not_charge():
    called=[]; r=Repository(0)
    import pytest
    with pytest.raises(ValueError): checkout(Order(1),r,lambda x: called.append(x))
    assert called == []
""",
    },
    "cache_invalidation": {
        "title": "Fix tenant cache invalidation",
        "description": "Ensure profile updates invalidate exactly the affected tenant/user cache entry.",
        "expected": "Reads never return stale profiles and other tenants remain cached.",
        "difficulty": "medium",
        "language": "Python",
        "tags": ["cache", "state", "multi-tenant"],
        "files": {
            "README.md": "# Profiles\n",
            "profiles/cache.py": """class Cache:
    def __init__(self): self.values={}
    def get(self,key): return self.values.get(key)
    def put(self,key,value): self.values[key]=dict(value)
    def delete(self,key): self.values.pop(key,None)
""",
            "profiles/service.py": """class ProfileService:
    def __init__(self, store, cache): self.store,self.cache=store,cache
    def get(self, tenant, user):
        key=user
        cached=self.cache.get(key)
        if cached is not None: return cached
        value=self.store[(tenant,user)]; self.cache.put(key,value); return value
    def update(self, tenant, user, value):
        self.store[(tenant,user)]=dict(value)
""",
            "tests/test_profiles.py": """from profiles.cache import Cache
from profiles.service import ProfileService
def test_read_through():
    s={('a','u'):{'name':'A'}}; service=ProfileService(s,Cache())
    assert service.get('a','u')['name']=='A'
""",
        },
        "reference": {"profiles/service.py": """class ProfileService:
    def __init__(self, store, cache): self.store,self.cache=store,cache
    @staticmethod
    def _key(tenant,user): return f'{tenant}:{user}'
    def get(self, tenant, user):
        key=self._key(tenant,user); cached=self.cache.get(key)
        if cached is not None: return cached
        value=self.store[(tenant,user)]; self.cache.put(key,value); return dict(value)
    def update(self, tenant, user, value):
        self.store[(tenant,user)]=dict(value); self.cache.delete(self._key(tenant,user))
"""},
        "official": """import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'candidate'))
from profiles.cache import Cache
from profiles.service import ProfileService

def test_tenant_isolation_and_invalidation():
    store={('a','u'):{'name':'A'},('b','u'):{'name':'B'}}; cache=Cache(); s=ProfileService(store,cache)
    assert s.get('a','u')['name']=='A' and s.get('b','u')['name']=='B'
    s.update('a','u',{'name':'AA'})
    assert s.get('a','u')['name']=='AA' and s.get('b','u')['name']=='B'

def test_returned_value_does_not_poison_cache():
    s=ProfileService({('a','u'):{'name':'A'}},Cache()); value=s.get('a','u'); value['name']='bad'
    assert s.get('a','u')['name']=='A'
""",
    },
    "bounded_retry": {
        "title": "Add bounded retry policy",
        "description": "Retry transient delivery failures with bounded exponential delays and no retry for permanent errors.",
        "expected": "At most max_attempts occur; only TransientError is retried.",
        "difficulty": "medium", "language": "Python", "tags": ["retry", "reliability", "timeouts"],
        "files": {
            "README.md": "# Delivery retry\n",
            "delivery/errors.py": "class TransientError(RuntimeError): pass\nclass PermanentError(RuntimeError): pass\n",
            "delivery/retry.py": """def deliver_with_retry(send, sleep, max_attempts=3, base_delay=0.1):
    return send()
""",
            "tests/test_retry.py": """from delivery.retry import deliver_with_retry
def test_success(): assert deliver_with_retry(lambda:'ok',lambda _:None)=='ok'
""",
        },
        "reference": {"delivery/retry.py": """from .errors import TransientError

def deliver_with_retry(send, sleep, max_attempts=3, base_delay=0.1):
    if max_attempts < 1: raise ValueError('max_attempts must be positive')
    for attempt in range(max_attempts):
        try: return send()
        except TransientError:
            if attempt + 1 == max_attempts: raise
            sleep(base_delay * (2 ** attempt))
    raise AssertionError('unreachable')
"""},
        "official": """import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'candidate'))
from delivery.errors import TransientError, PermanentError
from delivery.retry import deliver_with_retry

def test_bounded_backoff():
    calls=[]; delays=[]
    def send():
        calls.append(1)
        if len(calls)<3: raise TransientError()
        return 'ok'
    assert deliver_with_retry(send,delays.append,3,.25)=='ok'
    assert len(calls)==3 and delays==[.25,.5]

def test_permanent_not_retried():
    calls=[]
    import pytest
    with pytest.raises(PermanentError): deliver_with_retry(lambda:(calls.append(1) or (_ for _ in ()).throw(PermanentError())),lambda _:None)
    assert len(calls)==1
""",
    },
    "resource_cleanup": {
        "title": "Prevent streaming resource leaks",
        "description": "Close transport responses on success, parse failure, cancellation, and consumer early exit.",
        "expected": "stream_rows always closes the response exactly once.",
        "difficulty": "medium", "language": "Python", "tags": ["resources", "reliability", "generators"],
        "files": {
            "README.md": "# Streaming client\n",
            "streaming/parser.py": "def parse(line): return int(line)\n",
            "streaming/client.py": """from .parser import parse
def stream_rows(open_response):
    response=open_response()
    for line in response:
        yield parse(line)
""",
            "tests/test_client.py": """from streaming.client import stream_rows
class R(list):
    def close(self): self.closed=True
def test_rows(): assert list(stream_rows(lambda:R(['1','2'])))==[1,2]
""",
        },
        "reference": {"streaming/client.py": """from .parser import parse
def stream_rows(open_response):
    response=open_response()
    try:
        for line in response: yield parse(line)
    finally: response.close()
"""},
        "official": """import sys,gc
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'candidate'))
from streaming.client import stream_rows
class R(list):
    def __init__(self,*a): super().__init__(*a); self.closes=0
    def close(self): self.closes+=1

def test_success_and_parse_failure_close():
    r=R(['1']); assert list(stream_rows(lambda:r))==[1] and r.closes==1
    bad=R(['x']);
    import pytest
    with pytest.raises(ValueError): list(stream_rows(lambda:bad))
    assert bad.closes==1

def test_early_close():
    r=R(['1','2']); g=stream_rows(lambda:r); assert next(g)==1; g.close(); gc.collect(); assert r.closes==1
""",
    },
    "lock_inventory": {
        "title": "Make inventory reservation thread-safe",
        "description": "Repair a check-then-decrement race while preserving per-SKU concurrency.",
        "expected": "Concurrent reservations never oversell and unrelated SKUs do not share one global lock.",
        "difficulty": "hard", "language": "Python", "tags": ["concurrency", "locking", "state"],
        "files": {
            "README.md": "# Inventory\n",
            "inventory/store.py": """import time
class Inventory:
    def __init__(self, stock): self.stock=dict(stock)
    def reserve(self, sku, quantity=1):
        current=self.stock.get(sku,0)
        if current < quantity: return False
        time.sleep(.002)
        self.stock[sku]=current-quantity
        return True
""",
            "inventory/service.py": "def reserve_many(store, sku, quantity): return store.reserve(sku, quantity)\n",
            "tests/test_store.py": """from inventory.store import Inventory
def test_single(): s=Inventory({'x':1}); assert s.reserve('x') and not s.reserve('x')
""",
        },
        "reference": {"inventory/store.py": """import threading
class Inventory:
    def __init__(self, stock): self.stock=dict(stock); self._guard=threading.Lock(); self._locks={}
    def _lock(self,sku):
        with self._guard: return self._locks.setdefault(sku,threading.Lock())
    def reserve(self, sku, quantity=1):
        if quantity < 1: raise ValueError('quantity')
        with self._lock(sku):
            current=self.stock.get(sku,0)
            if current < quantity: return False
            self.stock[sku]=current-quantity; return True
"""},
        "official": """import sys,threading,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'candidate'))
from inventory.store import Inventory

def test_no_oversell():
    for _ in range(10):
        s=Inventory({'x':1}); barrier=threading.Barrier(8); out=[]
        def run(): barrier.wait(); out.append(s.reserve('x'))
        ts=[threading.Thread(target=run) for _ in range(8)]; [t.start() for t in ts]; [t.join() for t in ts]
        assert sum(out)==1 and s.stock['x']==0

def test_invalid_quantity():
    import pytest
    with pytest.raises(ValueError): Inventory({'x':1}).reserve('x',0)
""",
    },
    "cross_file_permissions": {
        "title": "Repair inherited authorization",
        "description": "Trace project membership, document ownership, and inherited organization roles across modules.",
        "expected": "can_edit applies tenant-safe owner, project editor, and organization admin rules.",
        "difficulty": "hard", "language": "Python", "tags": ["authorization", "cross-file", "security"],
        "files": {
            "README.md": "# Document authorization\n",
            "auth/models.py": """from dataclasses import dataclass
@dataclass(frozen=True)
class User: id:int; organization_id:int; role:str='member'
@dataclass(frozen=True)
class Document: owner_id:int; organization_id:int; project_id:int|None=None
""",
            "auth/membership.py": "def project_role(memberships,user_id,project_id): return memberships.get((user_id,project_id))\n",
            "auth/policy.py": """from .membership import project_role
def can_edit(user, document, memberships):
    return user.id == document.owner_id
""",
            "tests/test_policy.py": """from auth.models import *
from auth.policy import can_edit
def test_owner(): assert can_edit(User(1,2),Document(1,2),{})
""",
        },
        "reference": {"auth/policy.py": """from .membership import project_role
def can_edit(user, document, memberships):
    if user.organization_id != document.organization_id: return False
    if user.role == 'admin' or user.id == document.owner_id: return True
    return document.project_id is not None and project_role(memberships,user.id,document.project_id) == 'editor'
"""},
        "official": """import sys
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
""",
    },
    "extract_transport_refactor": {
        "title": "Extract a transport abstraction",
        "description": "Remove duplicated webhook delivery code while preserving headers, serialization, and errors.",
        "expected": "Email and audit clients share a Transport without behavioral changes.",
        "difficulty": "medium", "language": "Python", "tags": ["refactoring", "abstraction", "cross-file"],
        "files": {
            "README.md": "# Webhook clients\n",
            "hooks/email.py": """import json
class EmailHooks:
    def __init__(self,http,token): self.http,self.token=http,token
    def send(self,url,payload): return self.http.post(url,body=json.dumps(payload,sort_keys=True),headers={'Authorization':f'Bearer {self.token}','Content-Type':'application/json'},timeout=5)
""",
            "hooks/audit.py": """import json
class AuditHooks:
    def __init__(self,http,token): self.http,self.token=http,token
    def send(self,url,payload): return self.http.post(url,body=json.dumps(payload),headers={'Authorization':f'Bearer {self.token}'},timeout=10)
""",
            "tests/test_hooks.py": "def test_placeholder(): assert True\n",
        },
        "reference": {
            "hooks/transport.py": """import json
class Transport:
    def __init__(self,http,token): self.http,self.token=http,token
    def post(self,url,payload,timeout): return self.http.post(url,body=json.dumps(payload,sort_keys=True),headers={'Authorization':f'Bearer {self.token}','Content-Type':'application/json'},timeout=timeout)
""",
            "hooks/email.py": """from .transport import Transport
class EmailHooks:
    def __init__(self,http,token): self.transport=Transport(http,token)
    def send(self,url,payload): return self.transport.post(url,payload,5)
""",
            "hooks/audit.py": """from .transport import Transport
class AuditHooks:
    def __init__(self,http,token): self.transport=Transport(http,token)
    def send(self,url,payload): return self.transport.post(url,payload,10)
""",
        },
        "official": """import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'candidate'))
from hooks.email import EmailHooks
from hooks.audit import AuditHooks
class HTTP:
    def __init__(self): self.calls=[]
    def post(self,*a,**kw): self.calls.append((a,kw)); return 202
def test_both_clients_preserve_contract():
    http=HTTP(); assert EmailHooks(http,'t').send('/e',{'b':1,'a':2})==202; AuditHooks(http,'t').send('/a',{'b':1,'a':2})
    assert [c[1]['timeout'] for c in http.calls]==[5,10]
    for _,kw in http.calls:
        assert kw['body']=='{"a": 2, "b": 1}'
        assert kw['headers']=={'Authorization':'Bearer t','Content-Type':'application/json'}
def test_shared_abstraction_exists():
    from hooks.transport import Transport
    assert Transport
""",
    },
    "js_ttl_cache": {
        "title": "Repair TTL cache semantics",
        "description": "Fix expiration, falsy values, and monotonic clock injection in a JavaScript cache.",
        "expected": "Cache entries expire at the deadline and preserve false, zero, and empty strings.",
        "difficulty": "medium", "language": "TypeScript/JavaScript", "tags": ["javascript", "cache", "time"],
        "test_command": "node --test",
        "files": {
            "README.md": "# TTL cache\n",
            "package.json": "{\"type\":\"module\",\"scripts\":{\"test\":\"node --test\"}}\n",
            "src/cache.js": """export class TTLCache {
  constructor(now = Date.now) { this.now = now; this.values = new Map(); }
  set(key, value, ttlMs) { this.values.set(key, { value, expires: this.now() + ttlMs }); }
  get(key) { const item = this.values.get(key); return item?.value || undefined; }
}
""",
            "test/cache.test.js": """import test from 'node:test'; import assert from 'node:assert/strict'; import {TTLCache} from '../src/cache.js';
test('stores value',()=>{const c=new TTLCache(()=>0); c.set('x','v',10); assert.equal(c.get('x'),'v');});
""",
        },
        "reference": {"src/cache.js": """export class TTLCache {
  constructor(now = Date.now) { this.now = now; this.values = new Map(); }
  set(key, value, ttlMs) { if (ttlMs < 0) throw new RangeError('ttlMs'); this.values.set(key, { value, expires: this.now() + ttlMs }); }
  get(key) { const item = this.values.get(key); if (!item) return undefined; if (this.now() >= item.expires) { this.values.delete(key); return undefined; } return item.value; }
}
"""},
        "official": """import json, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'candidate'
def run(script):
    result=subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,text=True,capture_output=True)
    assert result.returncode==0, result.stderr
def test_expiry_and_falsy_values():
    run("import {TTLCache} from './src/cache.js'; let n=5; const c=new TTLCache(()=>n); for (const [k,v] of [['z',0],['f',false],['e','']]) c.set(k,v,2); if(c.get('z')!==0||c.get('f')!==false||c.get('e')!=='') process.exit(2); n=7; if(c.get('z')!==undefined) process.exit(3)")
def test_negative_ttl_rejected():
    run("import {TTLCache} from './src/cache.js'; try { new TTLCache(()=>0).set('x',1,-1); process.exit(2) } catch(e) { if(!(e instanceof RangeError)) process.exit(3) }")
""",
    },
    "js_batch_dedupe": {
        "title": "Deduplicate concurrent batch loads",
        "description": "Coalesce overlapping asynchronous key loads without sharing failures across later batches.",
        "expected": "Concurrent requests share in-flight keys; failures clear state for retry.",
        "difficulty": "hard", "language": "TypeScript/JavaScript", "tags": ["javascript", "concurrency", "batching"],
        "test_command": "node --test",
        "files": {
            "README.md": "# Batch loader\n",
            "package.json": "{\"type\":\"module\",\"scripts\":{\"test\":\"node --test\"}}\n",
            "src/loader.js": """export class Loader {
  constructor(load) { this.load = load; }
  async get(key) { const values = await this.load([key]); return values.get(key); }
}
""",
            "test/loader.test.js": """import test from 'node:test'; import assert from 'node:assert/strict'; import {Loader} from '../src/loader.js';
test('loads',async()=>{const l=new Loader(async ks=>new Map([[ks[0],1]])); assert.equal(await l.get('x'),1);});
""",
        },
        "reference": {"src/loader.js": """export class Loader {
  constructor(load) { this.load = load; this.inflight = new Map(); }
  get(key) {
    if (this.inflight.has(key)) return this.inflight.get(key);
    const promise = Promise.resolve().then(()=>this.load([key])).then(values=>values.get(key));
    this.inflight.set(key,promise);
    promise.finally(()=>{ if(this.inflight.get(key)===promise) this.inflight.delete(key); }).catch(()=>{});
    return promise;
  }
}
"""},
        "official": """import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'candidate'
def run(code):
    r=subprocess.run(['node','--input-type=module','-e',code],cwd=ROOT,text=True,capture_output=True); assert r.returncode==0,r.stderr
def test_concurrent_deduplication():
    run("import {Loader} from './src/loader.js'; let calls=0; const l=new Loader(async ks=>{calls++; await new Promise(r=>setTimeout(r,20)); return new Map([[ks[0],42]])}); const [a,b]=await Promise.all([l.get('x'),l.get('x')]); if(a!==42||b!==42||calls!==1) process.exit(2)")
def test_failure_can_retry():
    run("import {Loader} from './src/loader.js'; let calls=0; const l=new Loader(async ks=>{calls++; if(calls===1) throw Error('x'); return new Map([[ks[0],7]])}); try{await l.get('x')}catch{}; await new Promise(r=>setTimeout(r,0)); if(await l.get('x')!==7||calls!==2) process.exit(2)")
""",
    },
}


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    for task_id, definition in TASKS.items():
        task_dir = BENCHMARKS / "tasks" / task_id
        fixture_dir = BENCHMARKS / "fixtures" / task_id
        verification_dir = BENCHMARKS / "verification" / task_id
        reference_dir = BENCHMARKS / "reference" / task_id
        if any(path.exists() for path in (task_dir, fixture_dir, verification_dir, reference_dir)):
            raise SystemExit(f"refusing to overwrite frozen task {task_id}")
        for relative, content in definition["files"].items():
            write(fixture_dir / relative, content)
        for relative, content in definition["reference"].items():
            write(reference_dir / relative, content)
        write(verification_dir / "test_official.py", definition["official"])
        manifest = {
            "id": task_id,
            "title": definition["title"],
            "description": definition["description"],
            "repository": {"type": "local", "source": f"fixtures/{task_id}"},
            "setup_command": None,
            "test_command": definition.get("test_command", "python -m pytest -q"),
            "timeout_seconds": 180 if definition["difficulty"] == "hard" else 120,
            "expected_behavior": definition["expected"],
            "version": definition.get("version", "1.0.0"),
            "language": definition["language"],
            "difficulty": definition["difficulty"],
            "tags": definition["tags"],
            "provenance": {
                "source": "agentscope",
                "dataset": "AgentScope Benchmark",
                "dataset_version": "0.1",
                "source_task_id": task_id,
            },
            "verification": {
                "source": f"verification/{task_id}",
                "timeout_seconds": 45,
                "kind": "pytest",
            },
        }
        write(task_dir / "task.yaml", yaml.safe_dump(manifest, sort_keys=False))

    existing = BENCHMARKS / "tasks/incorrect_api_response/task.yaml"
    data = yaml.safe_load(existing.read_text(encoding="utf-8"))
    data.update(
        language="Python",
        difficulty="easy",
        provenance={
            "source": "agentscope",
            "dataset": "AgentScope Benchmark",
            "dataset_version": "0.1",
            "source_task_id": "incorrect_api_response",
        },
    )
    existing.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    print(json.dumps({"suite": "AgentScope Benchmark", "version": "0.1", "created": len(TASKS)}))


if __name__ == "__main__":
    main()
