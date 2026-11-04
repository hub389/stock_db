"""SDB1 — stock_db 分析專用二進位欄位格式（只需 numpy，無外加套件）

檔案結構：
  b"SDB1" | uint32 LE 表頭長度 | 表頭 JSON(UTF-8) | 資料區（多個 zlib 壓縮區塊）
表頭 JSON：
  {"kind":..., "cols":[{"n":名稱,"t":"i8|i16|i32|f64","s":倍率,"d":是否差分}],
   "blocks":[{"k":代號,"day":日期(可省),"r":列數,"o":資料區位移,"l":長度,"b":{差分欄起始值}}], ...}
區塊內容：各欄位陣列（小端序）依 cols 順序首尾相接後 zlib 壓縮。
  倍率 s：存整數，實際值 = 整數 / s（價格 s=100）。
  差分 d：存相鄰差值，實際值 = b[欄名] + 累加和。
"""
import json, struct, zlib
import numpy as np

DT = {"i8": np.int8, "i16": np.int16, "i32": np.int32, "f64": np.float64}
MAGIC = b"SDB1"


def encode_block(cols, data):
    """data: dict 欄名 -> numpy 陣列(實際值)。回傳 (壓縮位元組, 列數, base)"""
    parts, base, n = [], {}, None
    for c in cols:
        x = np.asarray(data[c["n"]])
        n = len(x) if n is None else n
        assert len(x) == n, c["n"]
        s = c.get("s", 1)
        if c["t"] == "f64":
            v = x.astype(np.float64)
            if c.get("d") and n:
                base[c["n"]] = float(v[0])
                v = np.diff(v, prepend=v[0])
        else:
            xi = np.round(x.astype(np.float64) * s) if s != 1 else x
            if s != 1:
                err = np.abs(x.astype(np.float64) * s - xi)
                if n and err.max() > 1e-6:
                    raise ValueError(f"{c['n']} 小數位超過 1/{s}")
            v = np.asarray(xi).astype(np.int64)
            if c.get("d") and n:
                base[c["n"]] = int(v[0])
                v = np.diff(v, prepend=v[0])
            info = np.iinfo(DT[c["t"]])
            if n and (v.min() < info.min or v.max() > info.max):
                raise OverflowError(f"{c['n']} 超出 {c['t']} 範圍")
            v = v.astype(DT[c["t"]])
        parts.append(v.astype(v.dtype.newbyteorder("<")).tobytes())
    return zlib.compress(b"".join(parts), 6), n or 0, base


def decode_block(cols, raw, rows, base):
    buf = zlib.decompress(raw)
    out, pos = {}, 0
    for c in cols:
        dt = np.dtype(DT[c["t"]]).newbyteorder("<")
        v = np.frombuffer(buf, dt, rows, pos)
        pos += rows * dt.itemsize
        if c.get("d"):
            v = base.get(c["n"], 0) + (np.cumsum(v) if c["t"] == "f64" else np.cumsum(v.astype(np.int64)))
        s = c.get("s", 1)
        if s != 1:
            out[c["n"]] = v / s
        elif c["t"] == "f64":
            out[c["n"]] = v.astype(np.int64) if c.get("d") else v
        else:
            out[c["n"]] = v.astype(np.int64)
    return out


def write_file(path, kind, cols, blocks, extra=None):
    """blocks: list of dict(k, day?, raw, r, b)"""
    hdr = {"kind": kind, "cols": cols, "blocks": []}
    if extra:
        hdr.update(extra)
    off = 0
    for b in blocks:
        e = {"k": b["k"], "r": b["r"], "o": off, "l": len(b["raw"])}
        if b.get("day") is not None:
            e["day"] = b["day"]
        if b.get("b"):
            e["b"] = b["b"]
        hdr["blocks"].append(e)
        off += len(b["raw"])
    hj = json.dumps(hdr, ensure_ascii=False, separators=(",", ":")).encode()
    with open(path, "wb") as f:
        f.write(MAGIC + struct.pack("<I", len(hj)) + hj)
        for b in blocks:
            f.write(b["raw"])


class SDB:
    """讀取：db = SDB('m1_202610.sdb'); df = db.get('3037'); db.keys()"""

    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            assert f.read(4) == MAGIC, "不是 SDB1 檔"
            hl = struct.unpack("<I", f.read(4))[0]
            self.hdr = json.loads(f.read(hl))
        self.start = 8 + hl
        self.cols = self.hdr["cols"]
        self.blocks = self.hdr["blocks"]

    def keys(self):
        return sorted({b["k"] for b in self.blocks})

    def _read(self, f, b):
        f.seek(self.start + b["o"])
        d = decode_block(self.cols, f.read(b["l"]), b["r"], b.get("b", {}))
        return d

    def get(self, code=None, day=None, as_df=True):
        """code=None 讀全部；day 只用於 TICK（按日分區塊）"""
        import pandas as pd
        sel = [b for b in self.blocks if (code is None or b["k"] == str(code))
               and (day is None or b.get("day") == int(day))]
        frames = []
        with open(self.path, "rb") as f:
            for b in sel:
                d = self._read(f, b)
                if not as_df:
                    frames.append((b, d)); continue
                df = pd.DataFrame(d)
                df.insert(0, "code", b["k"])
                if "day" in b:
                    df.insert(1, "date", b["day"])
                frames.append(df)
        if not as_df:
            return frames
        if not frames:
            return pd.DataFrame(columns=["code"] + [c["n"] for c in self.cols])
        return pd.concat(frames, ignore_index=True)
