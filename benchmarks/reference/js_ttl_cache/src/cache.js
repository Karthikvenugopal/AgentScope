export class TTLCache {
  constructor(now = Date.now) { this.now = now; this.values = new Map(); }
  set(key, value, ttlMs) { if (ttlMs < 0) throw new RangeError('ttlMs'); this.values.set(key, { value, expires: this.now() + ttlMs }); }
  get(key) { const item = this.values.get(key); if (!item) return undefined; if (this.now() >= item.expires) { this.values.delete(key); return undefined; } return item.value; }
}
