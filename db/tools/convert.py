"""把解開的 sj_data / day_data 轉成 SDB1 主庫，並逐筆往返核對。
用法: python3 convert.py <來源根目錄(含sj_data,day_data)> <輸出目錄> <組名(pool|excl)>
"""
import os, sys, glob, json, time
from collections import defaultdict
from multiprocessing import Pool
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from sdb import encode_block, decode_block, write_file

M1C = [{"n": "date", "t": "i32"}, {"n": "t", "t": "i16"},
       {"n": "open", "t": "i32", "s": 100}, {"n": "high", "t": "i32", "s": 100},
       {"n": "low", "t": "i32", "s": 100}, {"n": "close", "t": "i32", "s": 100},
       {"n": "volume", "t": "i32"}, {"n": "amount", "t": "f64"}]
TKC = [{"n": "t", "t": "f64", "d": True},
       {"n": "price", "t": "i32", "s": 100}, {"n": "volume", "t": "i32"},
       {"n": "bid_price", "t": "i32", "s": 100}, {"n": "bid_volume", "t": "i32"},
       {"n": "ask_price", "t": "i32", "s": 100}, {"n": "ask_volume", "t": "i32"},
       {"n": "tick_type", "t": "i8"}]
DYC = [{"n": "date", "t": "i32"},
       {"n": "open", "t": "i32", "s": 100}, {"n": "high", "t": "i32", "s": 100},
       {"n": "low", "t": "i32", "s": 100}, {"n": "close", "t": "i32", "s": 100},
       {"n": "volume", "t": "f64"}, {"n": "amount", "t": "f64"}]


def hms_min(s):
    p = s.str.split(":", expand=True).astype(int)
    if (p[2] != 0).any():
        raise ValueError("1分K 時間含秒")
    return (p[0] * 60 + p[1]).values


def hms_us(s):
    a = s.str.split(".", n=1, expand=True)
    p = a[0].str.split(":", expand=True).astype(np.int64)
    frac = a[1].fillna("") if a.shape[1] > 1 else pd.Series([""] * len(a))
    frac = frac.str.ljust(6, "0").str[:6].astype(np.int64)
    return ((p[0] * 3600 + p[1] * 60 + p[2]) * 1_000_000 + frac).values


def check(cols, raw, n, base, data):
    d = decode_block(cols, raw, n, base)
    for c in cols:
        a, b = np.asarray(data[c["n"]], dtype=np.float64), d[c["n"]].astype(np.float64)
        if not np.allclose(a, b, rtol=0, atol=1e-9):
            raise ValueError(f"往返核對失敗 {c['n']}")


def do_code(args):
    root, code = args
    out = {"code": code, "m1": {}, "tick": [], "m1_rows": {}, "tick_rows": {}, "err": []}
    d = os.path.join(root, "sj_data", code)
    # 1分K：依月份
    bym = defaultdict(list)
    for f in sorted(glob.glob(os.path.join(d, "m1_*.csv"))):
        day = int(f[-12:-4])
        if day == 20241201:
            continue
        try:
            df = pd.read_csv(f, dtype={"time": str})
        except pd.errors.EmptyDataError:
            out["err"].append(f"空檔 {os.path.basename(f)}"); continue
        if len(df) == 0:
            out["err"].append(f"0列 {os.path.basename(f)}"); continue
        df["date"] = day
        df["t"] = hms_min(df["time"])
        df = df.sort_values("t", kind="stable")
        if df["t"].duplicated().any():
            out["err"].append(f"1分K重複時間 {day}")
        bym[day // 100].append(df)
        out["m1_rows"][day] = len(df)
    for ym, lst in bym.items():
        df = pd.concat(lst, ignore_index=True)
        data = {c["n"]: df[c["n"]].values for c in M1C}
        raw, n, base = encode_block(M1C, data)
        check(M1C, raw, n, base, data)
        out["m1"][ym] = {"k": code, "raw": raw, "r": n, "b": base}
    # TICK：每日一區塊
    for f in sorted(glob.glob(os.path.join(d, "tick_*.csv"))):
        day = int(f[-12:-4])
        try:
            df = pd.read_csv(f, dtype={"time": str})
        except pd.errors.EmptyDataError:
            out["err"].append(f"空檔 {os.path.basename(f)}"); continue
        if len(df) == 0:
            out["err"].append(f"0列 {os.path.basename(f)}"); continue
        if "price" not in df and "close" in df:  # 加權指數 TICK 用 close
            df = df.rename(columns={"close": "price"})
        df["t"] = hms_us(df["time"])
        data = {c["n"]: df[c["n"]].values for c in TKC}
        raw, n, base = encode_block(TKC, data)
        check(TKC, raw, n, base, data)
        out["tick"].append({"k": code, "day": day, "raw": raw, "r": n, "b": base})
        out["tick_rows"][day] = n
    return out


def main():
    root, outdir, grp = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(outdir, exist_ok=True)
    t0 = time.time()
    codes = sorted(x for x in os.listdir(os.path.join(root, "sj_data"))
                   if os.path.isdir(os.path.join(root, "sj_data", x)))
    m1 = defaultdict(list); tick = defaultdict(list)
    man = {"m1": {}, "tick": {}, "err": {}}
    with Pool(2) as p:
        for i, r in enumerate(p.imap_unordered(do_code, [(root, c) for c in codes], chunksize=2)):
            for ym, b in r["m1"].items():
                m1[ym].append(b)
            for b in r["tick"]:
                tick[b["day"] // 100].append(b)
            man["m1"][r["code"]] = r["m1_rows"]
            man["tick"][r["code"]] = r["tick_rows"]
            if r["err"]:
                man["err"][r["code"]] = r["err"]
            if i % 50 == 0:
                print(i, len(codes), round(time.time() - t0), "s", flush=True)
    os.makedirs(f"{outdir}/m1", exist_ok=True); os.makedirs(f"{outdir}/tick", exist_ok=True)
    for ym, bl in m1.items():
        bl.sort(key=lambda b: b["k"])
        write_file(f"{outdir}/m1/m1_{ym}.sdb", "m1", M1C, bl, {"ym": ym})
    LIM = 90 * 1024 * 1024
    for ym, bl in tick.items():
        bl.sort(key=lambda b: (b["day"], b["k"]))
        days = sorted({b["day"] for b in bl})
        # 依日期切段，每檔 < 90MB
        segs, cur, size = [], [], 0
        for dday in days:
            dbl = [b for b in bl if b["day"] == dday]
            s = sum(len(b["raw"]) for b in dbl)
            if cur and size + s > LIM:
                segs.append(cur); cur, size = [], 0
            cur += dbl; size += s
        if cur:
            segs.append(cur)
        for sg in segs:
            a, z = sg[0]["day"], sg[-1]["day"]
            sg.sort(key=lambda b: (b["k"], b["day"]))
            write_file(f"{outdir}/tick/tick_{a}-{z}.sdb", "tick", TKC, sg)
    # 日K
    dbl = []
    man["day"] = {}
    for f in sorted(glob.glob(os.path.join(root, "day_data", "*.csv"))):
        code = os.path.basename(f)[:-4]
        if code.startswith("_"):
            continue
        df = pd.read_csv(f).sort_values("date")
        if df["date"].duplicated().any():
            man["err"].setdefault(code, []).append("日K重複日期")
        data = {c["n"]: df[c["n"]].values for c in DYC}
        raw, n, base = encode_block(DYC, data)
        check(DYC, raw, n, base, data)
        dbl.append({"k": code, "raw": raw, "r": n, "b": base})
        man["day"][code] = [int(df.date.min()), int(df.date.max()), n]
    write_file(f"{outdir}/daily.sdb", "daily", DYC, dbl)
    json.dump(man, open(f"{outdir}/_rows_{grp}.json", "w"))
    print("完成", round(time.time() - t0), "s")


if __name__ == "__main__":
    main()
