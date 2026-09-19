export class Loader {
  constructor(load) { this.load = load; }
  async get(key) { const values = await this.load([key]); return values.get(key); }
}
