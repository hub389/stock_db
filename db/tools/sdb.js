/* SDB1 讀取器（App 用，免外掛庫）
 * 用法：
 *   const db = await SDB.open(blobOrArrayBuffer);   // File、Blob 或 fetch 回來的 ArrayBuffer
 *   db.keys()                                       // 代號清單
 *   const rows = await db.get('3037', 20261030);    // TICK 指定日；1分K、日K 可省略日期
 *   rows -> { code, date?, cols: {欄名: 陣列}, length }
 * 只解壓需要的區塊；讀大檔時用 Blob.slice，不必整個載入記憶體。
 */
(function (g) {
  const SZ = { i8: 1, i16: 2, i32: 4, f64: 8 };
  async function inflate(buf) {
    const ds = new DecompressionStream('deflate');
    const s = new Blob([buf]).stream().pipeThrough(ds);
    return await new Response(s).arrayBuffer();
  }
  async function slice(src, a, b) {
    if (src instanceof Blob) return await src.slice(a, b).arrayBuffer();
    return src.slice(a, b);
  }
  class SDB {
    static async open(src) {
      const h = new DataView(await slice(src, 0, 8));
      const magic = String.fromCharCode(h.getUint8(0), h.getUint8(1), h.getUint8(2), h.getUint8(3));
      if (magic !== 'SDB1') throw new Error('不是 SDB1 檔');
      const hl = h.getUint32(4, true);
      const hdr = JSON.parse(new TextDecoder().decode(await slice(src, 8, 8 + hl)));
      return new SDB(src, hdr, 8 + hl);
    }
    constructor(src, hdr, start) { this.src = src; this.hdr = hdr; this.start = start; }
    keys() { return [...new Set(this.hdr.blocks.map(b => b.k))].sort(); }
    days(code) { return this.hdr.blocks.filter(b => b.k === String(code) && b.day).map(b => b.day); }
    async _decode(b) {
      const buf = await inflate(await slice(this.src, this.start + b.o, this.start + b.o + b.l));
      const dv = new DataView(buf), n = b.r, out = {};
      let pos = 0;
      for (const c of this.hdr.cols) {
        const a = new Float64Array(n), w = SZ[c.t];
        for (let i = 0; i < n; i++, pos += w) {
          a[i] = c.t === 'f64' ? dv.getFloat64(pos, true) : c.t === 'i32' ? dv.getInt32(pos, true)
               : c.t === 'i16' ? dv.getInt16(pos, true) : dv.getInt8(pos);
        }
        if (c.d) { let s = (b.b && b.b[c.n]) || 0; for (let i = 0; i < n; i++) { s += a[i]; a[i] = s; } }
        if (c.s && c.s !== 1) for (let i = 0; i < n; i++) a[i] = Math.round(a[i]) / c.s;
        out[c.n] = a;
      }
      return { code: b.k, date: b.day, cols: out, length: n };
    }
    async get(code, day) {
      const bl = this.hdr.blocks.filter(b => b.k === String(code) && (day == null || b.day === Number(day)));
      const parts = [];
      for (const b of bl) parts.push(await this._decode(b));
      if (parts.length <= 1) return parts[0] || null;
      return parts; // TICK 未指定日期時回傳各日陣列
    }
  }
  // TICK 時間欄 t 為「當日 0 點起的微秒」；轉 "HH:MM:SS.ffffff"
  SDB.usToStr = us => { const s = Math.floor(us / 1e6), f = String(us % 1e6).padStart(6, '0');
    const p = x => String(x).padStart(2, '0');
    return `${p(Math.floor(s / 3600))}:${p(Math.floor(s / 60) % 60)}:${p(s % 60)}.${f}`; };
  // 1分K 時間欄 t 為「當日 0 點起的分鐘」，541 = 09:01
  SDB.minToStr = m => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
  g.SDB = SDB;
})(typeof window !== 'undefined' ? window : globalThis);
