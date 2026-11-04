#!/usr/bin/env python3
"""stock_db 補檔上傳（手機／平板 Termux 用，只需內建 Python）
流程：讀雲端 manifest → 找出庫裡還沒有的檔案（新日期＋舊缺口補抓的） → 檢查完整性
      → 打包成 inbox 包 → 推送到 hub389/stock_db/inbox/
用法：python sdb_up.py          檢查＋打包＋推送
      python sdb_up.py check    只檢查不上傳
"""
import os, sys, json, csv, tarfile, time, subprocess, urllib.request, io

SJ = "/sdcard/Download/sj_data"     # 1分K、TICK：sj_data/<代號>/m1_、tick_
DAY = "/sdcard/Download/day_data"   # 日K：day_data/<代號>/d1_<代號>.csv 或 day_data/<代號>.csv
REPO = os.path.expanduser("~/stock_db")
OUT = os.path.expanduser("~/up")
LOG = os.path.expanduser("~/.sdb_sent.json")
MAN_URL = "https://raw.githubusercontent.com/hub389/stock_db/main/db/manifest.json"
REPORT = "/sdcard/Download/sdb_檢查報告.txt"


def load_manifest():
    req = urllib.request.Request(MAN_URL + "?t=%d" % time.time(), headers={"Cache-Control": "no-cache"})
    return json.load(urllib.request.urlopen(req, timeout=60))


def m1_info(p):
    n, vol = 0, 0
    with open(p, newline="") as f:
        for r in csv.DictReader(f):
            n += 1; vol += int(float(r["volume"]))
    return n, vol


def tick_vol(p):
    v = 0
    with open(p, newline="") as f:
        for r in csv.DictReader(f):
            if r["time"][:8] <= "13:30:00":
                v += int(float(r["volume"]))
    return v


def day_file(code):
    for p in (f"{DAY}/{code}/d1_{code}.csv", f"{DAY}/{code}.csv"):
        if os.path.exists(p):
            return p
    return None


def main():
    only_check = len(sys.argv) > 1 and sys.argv[1] == "check"
    t0 = time.time()
    man = load_manifest()
    cal = man["cal"]; ix = {d: i for i, d in enumerate(cal)}
    sent = json.load(open(LOG)) if os.path.exists(LOG) else {}
    gaps = {(g[0], g[1], g[2]) for g in man.get("known_gaps", [])}

    def in_db(kind, code, d):
        b = man[kind].get(code)
        return b is not None and d in ix and b[ix[d]] == "1"

    codes = sorted(man["m1"].keys())
    new = []  # (kind, code, date, path)
    for c in codes:
        d0 = f"{SJ}/{c}"
        if not os.path.isdir(d0):
            continue
        for fn in os.listdir(d0):
            if not fn.endswith(".csv") or "_" not in fn:
                continue
            kind = fn.split("_")[0]
            if kind not in ("m1", "tick"):
                continue
            try:
                d = int(fn[-12:-4])
            except ValueError:
                continue
            if d == 20241201 or in_db(kind, c, d) or sent.get(f"{kind}/{c}/{d}"):
                continue
            new.append((kind, c, d, f"{d0}/{fn}"))
    # 新交易日：本次有 ≥100 檔 1分K 的日期
    cnt = {}
    for k, c, d, p in new:
        if k == "m1":
            cnt[d] = cnt.get(d, 0) + 1
    newdays = sorted(d for d, n in cnt.items() if n >= 100 and d not in ix)
    have = {(k, c, d): p for k, c, d, p in new}
    # 日K新增列
    dnew = {}
    for c in man["day"].keys():
        p = day_file(c)
        if not p:
            continue
        last = man["day"][c][1]
        with open(p, newline="") as f:
            rd = csv.DictReader(f)
            rows = [r for r in rd if int(r["date"]) > last and not sent.get(f"day/{c}/{r['date']}")]
        if rows:
            dnew[c] = rows
    # 檢查
    prob = []
    for d in newdays:
        for c in codes:
            m = have.get(("m1", c, d)); t = have.get(("tick", c, d))
            if (c, d, "m1") not in gaps and not m:
                prob.append(f"{c} {d} 缺1分K")
            if c != "101" and (c, d, "tick") not in gaps and not t:
                prob.append(f"{c} {d} 缺TICK")
            if m and t and c not in ("001", "101"):
                n, mv = m1_info(m)
                tv = tick_vol(t)
                if tv != mv:
                    prob.append(f"{c} {d} TICK量{tv}≠1分K量{mv}")
            if c in man["day"] and (c, d, "day") not in gaps:
                if not any(int(r["date"]) == d for r in dnew.get(c, [])):
                    prob.append(f"{c} {d} 缺日K")
    oldfill = sum(1 for k, c, d, p in new if d in ix)
    msg = [f"新交易日 {len(newdays)} 天：{newdays[0] if newdays else '-'} ~ {newdays[-1] if newdays else '-'}",
           f"待上傳：1分K {sum(1 for x in new if x[0]=='m1')} 檔、TICK {sum(1 for x in new if x[0]=='tick')} 檔、"
           f"日K {len(dnew)} 檔（其中補舊缺口 {oldfill} 檔）",
           f"問題 {len(prob)} 項" + ("：" if prob else "，資料完整")]
    grp = {}
    for p in prob:
        c, d, what = p.split(" ", 2)
        key = what if "≠" not in what else "TICK量≠1分K量"
        grp.setdefault((d, key), []).append(c)
    for (d, key), cs in sorted(grp.items()):
        msg.append(f"{d} {key} {len(cs)} 檔：" + "、".join(cs[:15]) + ("…" if len(cs) > 15 else ""))
    open(REPORT, "w").write("\n".join(msg[:3] + prob) + "\n")
    print("\n".join(msg))
    print(f"報告：{REPORT}　檢查 {time.time()-t0:.0f} 秒")
    if only_check or (not new and not dnew):
        return
    # 打包
    os.makedirs(OUT, exist_ok=True)
    ds = sorted({d for _, _, d, _ in new} | {int(r["date"]) for v in dnew.values() for r in v})
    name = f"inbox_{ds[0]}-{ds[-1]}_{time.strftime('%m%d%H%M')}.tar.gz"
    pkg = f"{OUT}/{name}"
    with tarfile.open(pkg, "w:gz") as tf:
        for k, c, d, p in new:
            tf.add(p, f"sj_data/{c}/{os.path.basename(p)}")
        for c, rows in dnew.items():
            b = io.StringIO(); w = csv.DictWriter(b, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
            data = b.getvalue().encode()
            ti = tarfile.TarInfo(f"day_data/{c}.csv"); ti.size = len(data); ti.mtime = time.time()
            tf.addfile(ti, io.BytesIO(data))
    sz = os.path.getsize(pkg)
    parts = [pkg]
    if sz > 90 * 1024 * 1024:  # GitHub 單檔上限 100MB
        parts = []
        with open(pkg, "rb") as f:
            i = 0
            while True:
                ch = f.read(90 * 1024 * 1024)
                if not ch:
                    break
                pp = f"{pkg}.part{i:02d}"; open(pp, "wb").write(ch); parts.append(pp); i += 1
        os.remove(pkg)
    print(f"打包 {name}（{sz/1e6:.1f}MB，{len(parts)} 檔）")
    # 推送：不下載舊大檔，只把新檔加到 inbox/
    g = lambda *a, **kw: subprocess.run(["git", "-C", REPO, *a], check=True, capture_output=True, text=True, **kw).stdout.strip()
    if not os.path.isdir(f"{REPO}/.git"):
        subprocess.run(["git", "clone", "--depth", "1", "--filter=blob:none", "--no-checkout",
                        "https://github.com/hub389/stock_db.git", REPO], check=True)
    g("config", "http.postBuffer", "524288000")
    g("fetch", "--depth", "1", "--filter=blob:none", "origin", "main")
    env = dict(os.environ, GIT_INDEX_FILE=f"{REPO}/.git/sdb_index")
    g("read-tree", "FETCH_HEAD", env=env)
    for pp in parts:
        h = g("hash-object", "-w", pp)
        g("update-index", "--add", "--cacheinfo", f"100644,{h},inbox/{os.path.basename(pp)}", env=env)
    tree = g("write-tree", env=env)
    cm = g("commit-tree", tree, "-p", "FETCH_HEAD", "-m", f"inbox {name}")
    g("push", "origin", f"{cm}:refs/heads/main")
    for k, c, d, p in new:
        sent[f"{k}/{c}/{d}"] = 1
    for c, rows in dnew.items():
        for r in rows:
            sent[f"day/{c}/{r['date']}"] = 1
    json.dump(sent, open(LOG, "w"))
    print(f"推送完成：inbox/{name}　共 {time.time()-t0:.0f} 秒")


if __name__ == "__main__":
    main()
