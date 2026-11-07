"""把 inbox 增量包合併進 SDB1 主庫（同代號同日期以新資料為準）
用法: python3 merge.py <db目錄> <inbox包1(.tar.gz 或 .part00)> [包2 ...]
"""
import os, sys, glob, tarfile, tempfile, shutil, io
from collections import defaultdict
from multiprocessing import Pool
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from sdb import SDB, encode_block, decode_block, write_file
from convert import M1C, TKC, DYC, do_code, check

LIM = 90 * 1024 * 1024


def raw_of(sdb, b):
    with open(sdb.path, "rb") as f:
        f.seek(sdb.start + b["o"]); return f.read(b["l"])


def open_pkg(p):
    if ".part" in p:
        base = p.split(".part")[0]
        data = b"".join(open(x, "rb").read() for x in sorted(glob.glob(base + ".part*")))
        return tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
    return tarfile.open(p, "r:gz")


def main():
    db, pkgs = sys.argv[1], sys.argv[2:]
    keep = len(pkgs) == 1 and os.path.isdir(pkgs[0])  # 已解開的目錄
    tmp = pkgs[0] if keep else tempfile.mkdtemp()
    done = set()
    for p in ([] if keep else pkgs):
        key = p.split(".part")[0]
        if key in done:
            continue
        done.add(key)
        with open_pkg(p) as tf:
            for m in tf.getmembers():
                if m.isfile() and (m.name.startswith("sj_data/") or m.name.startswith("day_data/")) and ".." not in m.name:
                    tf.extract(m, tmp, filter="data")
    codes = sorted(os.listdir(f"{tmp}/sj_data")) if os.path.isdir(f"{tmp}/sj_data") else []
    with Pool(2) as pl:
        res = pl.map(do_code, [(tmp, c) for c in codes])
    errs = {r["code"]: r["err"] for r in res if r["err"]}
    # 1分K：依月份合併
    newm = defaultdict(dict)
    for r in res:
        for ym, b in r["m1"].items():
            newm[ym][r["code"]] = b
    for ym, nb in newm.items():
        path = f"{db}/m1/m1_{ym}.sdb"
        out = {}
        if os.path.exists(path):
            s = SDB(path)
            for b in s.blocks:
                out[b["k"]] = {"k": b["k"], "raw": raw_of(s, b), "r": b["r"], "b": b.get("b", {})}
        for code, b in nb.items():
            if code in out:
                o = out[code]
                od = pd.DataFrame(decode_block(M1C, o["raw"], o["r"], o["b"]))
                nd = pd.DataFrame(decode_block(M1C, b["raw"], b["r"], b["b"]))
                od = od[~od.date.isin(nd.date.unique())]
                df = pd.concat([od, nd]).sort_values(["date", "t"], kind="stable")
                data = {c["n"]: df[c["n"]].values for c in M1C}
                raw, n, base = encode_block(M1C, data); check(M1C, raw, n, base, data)
                out[code] = {"k": code, "raw": raw, "r": n, "b": base}
            else:
                out[code] = b
        write_file(path, "m1", M1C, [out[k] for k in sorted(out)], {"ym": ym})
    # TICK：依月份重新切檔（未變動區塊直接沿用壓縮資料）
    newt = defaultdict(list)
    for r in res:
        for b in r["tick"]:
            newt[b["day"] // 100].append(b)
    for ym, nb in newt.items():
        keys = {(b["k"], b["day"]) for b in nb}
        bl = list(nb)
        olds = [p for p in glob.glob(f"{db}/tick/tick_*.sdb") if int(os.path.basename(p)[5:11]) == ym]
        for p in olds:
            s = SDB(p)
            for b in s.blocks:
                if (b["k"], b["day"]) not in keys:
                    bl.append({"k": b["k"], "day": b["day"], "raw": raw_of(s, b), "r": b["r"], "b": b.get("b", {})})
        for p in olds:
            os.remove(p)
        days = sorted({b["day"] for b in bl})
        segs, cur, size = [], [], 0
        for d in days:
            dbl = [b for b in bl if b["day"] == d]
            sz = sum(len(b["raw"]) for b in dbl)
            if cur and size + sz > LIM:
                segs.append(cur); cur, size = [], 0
            cur += dbl; size += sz
        if cur:
            segs.append(cur)
        for sg in segs:
            a, z = min(b["day"] for b in sg), max(b["day"] for b in sg)
            sg.sort(key=lambda b: (b["k"], b["day"]))
            write_file(f"{db}/tick/tick_{a}-{z}.sdb", "tick", TKC, sg)
    # 日K
    dd = f"{tmp}/day_data"
    if os.path.isdir(dd):
        s = SDB(f"{db}/daily.sdb")
        out = {b["k"]: {"k": b["k"], "raw": raw_of(s, b), "r": b["r"], "b": b.get("b", {})} for b in s.blocks}
        for f in glob.glob(f"{dd}/*.csv"):
            code = os.path.basename(f)[:-4]
            nd = pd.read_csv(f)
            if code in out:
                o = out[code]
                od = pd.DataFrame(decode_block(DYC, o["raw"], o["r"], o["b"]))
                od = od[~od.date.isin(nd.date)]
                nd = pd.concat([od, nd[[c["n"] for c in DYC]]])
            nd = nd.sort_values("date")
            data = {c["n"]: nd[c["n"]].values for c in DYC}
            raw, n, base = encode_block(DYC, data); check(DYC, raw, n, base, data)
            out[code] = {"k": code, "raw": raw, "r": n, "b": base}
        write_file(f"{db}/daily.sdb", "daily", DYC, [out[k] for k in sorted(out)])
    if not keep:
        shutil.rmtree(tmp)
    print("合併完成：1分K", sum(len(v) for v in newm.values()), "區塊，TICK",
          sum(len(v) for v in newt.values()), "區塊", "；異常", errs if errs else "無")


if __name__ == "__main__":
    main()
