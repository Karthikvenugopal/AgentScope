export class TTLCache {
  constructor(now = Date.now) { this.now = now; this.values = new Map(); }
  set(key, value, ttlMs) { this.values.set(key, { value, expires: this.now() + ttlMs }); }
  get(key) { const item = this.values.get(key); return item?.value || undefined; }
}
