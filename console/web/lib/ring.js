export class Ring {
  constructor(cap = 2000, block = 200) { this.cap = cap; this.block = block; this.items = []; this.dropped = 0; }
  push(item) {
    this.items.push(item);
    if (this.items.length > this.cap) { this.items.splice(0, this.block); this.dropped += this.block; }
  }
  get length() { return this.items.length; }
  last(n) { return n ? this.items.slice(-n) : this.items; }
  clear() { this.items = []; }
}
