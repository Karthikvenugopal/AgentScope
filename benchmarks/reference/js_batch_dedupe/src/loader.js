export class Loader {
  constructor(load) { this.load = load; this.inflight = new Map(); }
  get(key) {
    if (this.inflight.has(key)) return this.inflight.get(key);
    const promise = Promise.resolve().then(()=>this.load([key])).then(values=>values.get(key));
    this.inflight.set(key,promise);
    promise.finally(()=>{ if(this.inflight.get(key)===promise) this.inflight.delete(key); }).catch(()=>{});
    return promise;
  }
}
