"""建立 trial.sdb（盤前／收盤試撮）與 daily_n.sdb（非還原日K）
用法: python3 build_new.py <db目錄> <解開的inbox目錄>
trial：每檔每日一區塊；t=當日微秒，ses 0=盤前(08:30~09:00) 1=收盤(13:25~13:30)；bid/ask 空值存 0
"""
import os, sys, glob
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from sdb import SDB, encode_block, decode_block, write_file
from convert import DYC, hms_us, check
TRC = [{"n": "t", "t": "f64", "d": True}, {"n": "price", "t": "i32", "s": 100}, {"n": "volume", "t": "i32"},
       {"n": "bid", "t": "i32", "s": 100}, {"n": "ask", "t": "i32", "s": 100}, {"n": "ses", "t": "i8"}]


def raw_of(s, b):
    with open(s.path, "rb") as f:
        f.seek(s.start + b["o"]); return f.read(b["l"])


def main():
    db, inx = sys.argv[1], sys.argv[2]
    # 試撮（同代號同日以新檔為準）
    bl = {}
    p = f"{db}/trial.sdb"
    if os.path.exists(p):
        s = SDB(p)
        for b in s.blocks:
            bl[(b["k"], b["day"])] = {"k": b["k"], "day": b["day"], "raw": raw_of(s, b), "r": b["r"], "b": b.get("b", {})}
    n = 0
    for f in sorted(glob.glob(f"{inx}/sj_data/*/trial_*.csv")):
        code, day = f.split("/")[-2], int(f[-12:-4])
        df = pd.read_csv(f, dtype={"time": str})
        if not len(df):
            continue
        df["t"] = hms_us(df["time"])
        df = df.sort_values("t", kind="stable")
        df["ses"] = (df["session"] == "close").astype(int)
        df["bid"] = df["bid"].fillna(0); df["ask"] = df["ask"].fillna(0)
        data = {c["n"]: df[c["n"]].values for c in TRC}
        raw, r, base = encode_block(TRC, data); check(TRC, raw, r, base, data)
        bl[(code, day)] = {"k": code, "day": day, "raw": raw, "r": r, "b": base}
        n += 1
    write_file(p, "trial", TRC, [bl[k] for k in sorted(bl)],
               {"note": "富果試撮；t=當日微秒；volume=試撮累計量(張)；ses 0=盤前 1=收盤；bid/ask 0=無"})
    print("trial", n, "檔 →", len(bl), "區塊")
    # 非還原日K
    out = {}
    p = f"{db}/daily_n.sdb"
    if os.path.exists(p):
        s = SDB(p)
        for b in s.blocks:
            out[b["k"]] = pd.DataFrame(decode_block(DYC, raw_of(s, b), b["r"], b.get("b", {})))
    for f in glob.glob(f"{inx}/day_n/*.csv"):
        code = os.path.basename(f)[:-4]
        nd = pd.read_csv(f)
        if code in out:
            od = out[code]; nd = pd.concat([od[~od.date.isin(nd.date)], nd[[c["n"] for c in DYC]]])
        out[code] = nd.sort_values("date")
    blocks = []
    for code in sorted(out):
        d = out[code]
        data = {c["n"]: d[c["n"]].values for c in DYC}
        raw, r, base = encode_block(DYC, data); check(DYC, raw, r, base, data)
        blocks.append({"k": code, "raw": raw, "r": r, "b": base})
    write_file(p, "daily", DYC, blocks, {"note": "非還原日K（原始成交價）；量單位同 daily.sdb"})
    print("daily_n", len(blocks), "檔")


if __name__ == "__main__":
    main()
