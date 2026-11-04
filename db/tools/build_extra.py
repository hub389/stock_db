"""產生 feat.sdb（每日特徵摘要）、txf.sdb、manifest.json
用法: python3 build_extra.py <db目錄> <台指期zip> <pool _stocks.csv(sj_data)> <日K來源 _stocks.csv(含day_src)>
"""
import os, sys, glob, json, hashlib, zipfile, io, time
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from sdb import SDB, encode_block, decode_block, write_file

db = sys.argv[1]
FTC = [{"n": "date", "t": "i32"}, {"n": "bars", "t": "i16"},
       {"n": "pc", "t": "i32", "s": 100}, {"n": "open", "t": "i32", "s": 100},
       {"n": "high", "t": "i32", "s": 100}, {"n": "low", "t": "i32", "s": 100},
       {"n": "close", "t": "i32", "s": 100}, {"n": "volume", "t": "f64"}, {"n": "amount", "t": "f64"},
       {"n": "c5", "t": "i32", "s": 100}, {"n": "c15", "t": "i32", "s": 100}, {"n": "c30", "t": "i32", "s": 100},
       {"n": "c60", "t": "i32", "s": 100},
       {"n": "v5", "t": "f64"}, {"n": "v15", "t": "f64"}, {"n": "v30", "t": "f64"}, {"n": "v60", "t": "f64"},
       {"n": "h30", "t": "i32", "s": 100}, {"n": "l30", "t": "i32", "s": 100},
       {"n": "ht", "t": "i16"}, {"n": "lt", "t": "i16"}]
TXC = [{"n": "date", "t": "i32"}, {"n": "t", "t": "i16"},
       {"n": "open", "t": "i32"}, {"n": "high", "t": "i32"}, {"n": "low", "t": "i32"},
       {"n": "close", "t": "i32"}, {"n": "volume", "t": "i32"}]


def feats(g):
    """g: 單一股票全部 1分K（已依 date,t 排序）"""
    rows = []
    for d, x in g.groupby("date", sort=True):
        x = x[x.t <= 810]  # 到 13:30 為止
        if not len(x):
            continue
        t = x.t.values; c = x.close.values; v = x.volume.values.astype(float)
        hi = x.high.values; lo = x.low.values

        def at(m):
            k = np.searchsorted(t, 540 + m, side="right") - 1
            return (c[k], v[:k + 1].sum()) if k >= 0 else (np.nan, 0.0)
        r = {"date": d, "bars": len(x), "open": x.open.values[0], "high": hi.max(), "low": lo.min(),
             "close": c[-1], "volume": v.sum(), "amount": x.amount.values.sum()}
        for m in (5, 15, 30, 60):
            r[f"c{m}"], r[f"v{m}"] = at(m)
        k30 = t <= 570
        r["h30"] = hi[k30].max() if k30.any() else np.nan
        r["l30"] = lo[k30].min() if k30.any() else np.nan
        r["ht"] = t[int(np.argmax(hi))]; r["lt"] = t[int(np.argmin(lo))]
        rows.append(r)
    f = pd.DataFrame(rows)
    f["pc"] = f.close.shift(1)
    return f


t0 = time.time()
m1files = sorted(glob.glob(f"{db}/m1/m1_*.sdb"))
allm = {}
rows = {"m1": {}, "tick": {}, "day": {}}
for p in m1files:
    for b, d in SDB(p).get(as_df=False):
        allm.setdefault(b["k"], []).append(pd.DataFrame(d))
        u, n = np.unique(d["date"], return_counts=True)
        rows["m1"].setdefault(b["k"], {}).update({int(a): int(m) for a, m in zip(u, n)})
for p in sorted(glob.glob(f"{db}/tick/tick_*.sdb")):
    for b in SDB(p).blocks:
        rows["tick"].setdefault(b["k"], {})[b["day"]] = b["r"]
for b, d in SDB(f"{db}/daily.sdb").get(as_df=False):
    rows["day"][b["k"]] = [int(d["date"].min()), int(d["date"].max()), int(b["r"])]
blocks = []
for code, lst in sorted(allm.items()):
    g = pd.concat(lst, ignore_index=True).sort_values(["date", "t"], kind="stable")
    f = feats(g)
    data = {}
    for c in FTC:
        x = f[c["n"]].values.astype(float)
        if c["t"] != "f64":
            x = np.nan_to_num(x, nan=0.0)  # 缺值以 0 表示（如首日 pc、未到該時點）
        data[c["n"]] = x
    raw, n, base = encode_block(FTC, data)
    blocks.append({"k": code, "raw": raw, "r": n, "b": base})
write_file(f"{db}/feat.sdb", "feat", FTC, blocks,
           {"note": "1分K彙總(到13:30)。pc=前一交易日1分K收盤(原始價)；cN/vN=開盤後N分鐘(09:00+N)收盤與累積量；"
                    "h30/l30=09:30前高低；ht/lt=當日最高/最低出現分鐘(541=09:01)；0=無值"})
print("feat", round(time.time() - t0), "s")

# 台指期
z = zipfile.ZipFile(sys.argv[2]); tl = []
for nm in sorted(z.namelist()):
    if not nm.endswith(".csv"):
        continue
    df = pd.read_csv(io.BytesIO(z.read(nm)), dtype={"datetime": str})
    tl.append(df)
tx = pd.concat(tl, ignore_index=True)
dt = tx["datetime"].str.split(" ", expand=True)
tx["date"] = dt[0].str.replace("-", "").astype(int)
hm = dt[1].str.split(":", expand=True).astype(int)
tx["t"] = hm[0] * 60 + hm[1]
n0 = len(tx)
tx = tx.drop_duplicates(["date", "t"], keep="first")
bad = {20240831, 20241031, 20251122, 20251206, 20260131}
tx = tx[~tx.date.isin(bad)].sort_values(["date", "t"])
data = {c["n"]: tx[c["n"]].values for c in TXC}
raw, n, base = encode_block(TXC, data)
d2 = decode_block(TXC, raw, n, base)
assert all(np.array_equal(d2[c["n"]], tx[c["n"]].values) for c in TXC)
write_file(f"{db}/txf.sdb", "txf", TXC, [{"k": "TXF", "raw": raw, "r": n, "b": base}],
           {"note": "台指期日盤1分K 08:46~13:45；已去重複列、排除颱風停市等非交易日"})
print("txf rows", n0, "->", n, "days", tx.date.nunique())

# manifest
old = json.load(open(f"{db}/manifest.json")) if os.path.exists(f"{db}/manifest.json") else {}
st = pd.read_csv(sys.argv[3], dtype=str)
src = pd.read_csv(sys.argv[4], dtype=str).set_index("code")["day_src"].to_dict()
cal = sorted({int(d) for c in rows["m1"] for d in rows["m1"][c]})
cnt = pd.Series([int(d) for c in rows["m1"] for d in rows["m1"][c]]).value_counts()
cal = sorted(d for d in cal if cnt[d] >= 100)
tcal = sorted({int(d) for c in rows["tick"] for d in rows["tick"][c]})
ix = {d: i for i, d in enumerate(cal)}


def bits(dd):
    s = ["0"] * len(cal)
    for d in dd:
        if int(d) in ix:
            s[ix[int(d)]] = "1"
    return "".join(s)


codes = {}
for _, r in st.iterrows():
    codes[r.code] = {"name": r["name"], "ex": r.exchange, "ind": r.industry}
for c, v in src.items():
    codes.setdefault(c, {})["day_src"] = v
files = []
for p in sorted(glob.glob(f"{db}/**/*", recursive=True)):
    if not os.path.isfile(p) or p.endswith(("manifest.json", ".log")) or "/_" in p:
        continue
    h = hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]
    files.append({"f": os.path.relpath(p, db), "size": os.path.getsize(p), "sha": h})
man = {
    "format": "SDB1", "updated": time.strftime("%Y-%m-%d %H:%M"),
    "cal": cal,
    "range": {"m1": [cal[0], cal[-1]], "tick": [tcal[0], tcal[-1]],
              "day": [min(v[0] for v in rows["day"].values()), max(v[1] for v in rows["day"].values())]},
    "codes": codes,
    "m1": {c: bits(v) for c, v in sorted(rows["m1"].items())},
    "tick": {c: bits(v) for c, v in sorted(rows["tick"].items())},
    "day": rows["day"],
    "known_gaps": old.get("known_gaps", []),
    "files": files,
}
json.dump(man, open(f"{db}/manifest.json", "w"), ensure_ascii=False, separators=(",", ":"))
print("manifest", len(cal), "days", round(time.time() - t0), "s")
