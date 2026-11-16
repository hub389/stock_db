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
PENDING = os.path.expanduser("~/.sdb_pending.json")
MAN_URL = "https://raw.githubusercontent.com/hub389/stock_db/main/db/manifest.json"
REPORT = "/sdcard/Download/sdb_檢查報告.txt"
TICK_FROM = 20260102  # TICK 只收 2026 年起


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


def g(*a, env=None):
    r = subprocess.run(["git", "-C", REPO, *a], capture_output=True, text=True, env=env)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[-600:])
    return r.stdout.strip()


def push_pending(t0):
    """推送 ~/up 內待上傳的包；失敗可重跑，不必重新打包"""
    pd_ = json.load(open(PENDING))
    if not os.path.isdir(f"{REPO}/.git"):
        subprocess.run(["git", "clone", "--depth", "1", "--filter=blob:none", "--no-checkout",
                        "https://github.com/hub389/stock_db.git", REPO], check=True)
    g("config", "http.postBuffer", "524288000")
    for i in range(1, 4):
        try:
            g("fetch", "--depth", "1", "--filter=blob:none", "origin", "main")
            env = dict(os.environ, GIT_INDEX_FILE=f"{REPO}/.git/sdb_index")
            g("read-tree", "FETCH_HEAD", env=env)
            for pp in pd_["parts"]:
                h = g("hash-object", "-w", pp)
                g("update-index", "--add", "--cacheinfo", f"100644,{h},inbox/{os.path.basename(pp)}", env=env)
            tree = g("write-tree", env=env)
            cm = g("commit-tree", tree, "-p", "FETCH_HEAD", "-m", f"inbox {pd_['name']}")
            print(f"上傳中（第 {i} 次，{len(pd_['parts'])} 檔）…", flush=True)
            r = subprocess.run(["git", "-C", REPO, "push", "--progress", "origin", f"{cm}:refs/heads/main"])
            if r.returncode == 0:
                break
        except RuntimeError as e:
            print("git 錯誤：", e)
        if i == 3:
            sys.exit("推送失敗 3 次（多半是網路中斷）。網路恢復後再執行一次即可，會直接續傳、不必重新打包。")
        print("推送失敗，30 秒後自動重試…", flush=True)
        time.sleep(30)
    sent = json.load(open(LOG)) if os.path.exists(LOG) else {}
    for k in pd_["keys"]:
        sent[k] = 1
    json.dump(sent, open(LOG, "w"))
    for pp in pd_["parts"]:
        if os.path.exists(pp):
            os.remove(pp)
    os.remove(PENDING)
    print(f"推送完成：inbox/{pd_['name']}　共 {time.time()-t0:.0f} 秒")


def recover_v11():
    """V1.1 推送失敗留下的包：從包內清單重建待上傳記錄"""
    if os.path.exists(PENDING) or not os.path.isdir(OUT):
        return
    names = sorted({f.split(".tar.gz")[0] for f in os.listdir(OUT) if f.startswith("inbox_") and ".tar.gz" in f})
    if not names:
        return
    nm = names[-1]
    parts = sorted(f"{OUT}/{f}" for f in os.listdir(OUT) if f.startswith(nm + ".tar.gz"))
    print(f"發現上次未完成的包 {nm}（{len(parts)} 檔），讀取清單中（約 1~3 分鐘）…", flush=True)

    class Cat:
        def __init__(s, ps): s.ps, s.i, s.f = ps, 0, open(ps[0], "rb")
        def read(s, n=-1):
            out = b""
            while n < 0 or len(out) < n:
                b = s.f.read(-1 if n < 0 else n - len(out))
                if b: out += b; continue
                s.f.close(); s.i += 1
                if s.i >= len(s.ps): break
                s.f = open(s.ps[s.i], "rb")
            return out
    keys = []
    with tarfile.open(fileobj=Cat(parts), mode="r|gz") as tf:
        for m in tf:
            p = m.name.split("/")
            if p[0] == "sj_data" and len(p) == 3:
                fn = p[2]; keys.append(f"{fn.split('_')[0]}/{p[1]}/{fn[-12:-4]}")
            elif p[0] == "day_data":
                pass  # 日K 列由日期判斷，重新比對即可
    json.dump({"name": nm + ".tar.gz", "parts": parts, "keys": keys}, open(PENDING, "w"))
    print(f"清單 {len(keys)} 檔，續傳…")


def main():
    t0 = time.time()
    recover_v11()
    if os.path.exists(PENDING):
        push_pending(t0)
        print("如還有新資料，再執行一次即可。")
        return
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
            if d == 20241201 or (kind == "tick" and d < TICK_FROM) or in_db(kind, c, d) or sent.get(f"{kind}/{c}/{d}"):
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
    # TICK 涵蓋檢查（2026 年起；庫內＋本次待上傳）
    cov, full = [], 0
    for d in cal + newdays:
        if d < TICK_FROM:
            continue
        cs = [c for c in codes if c != "101" and (in_db("m1", c, d) or ("m1", c, d) in have)
              and (c, d, "tick") not in gaps]
        miss = [c for c in cs if not in_db("tick", c, d) and ("tick", c, d) not in have
                and not sent.get(f"tick/{c}/{d}")]
        if not miss:
            full += 1
        else:
            cov.append((d, len(miss), len(cs), miss))
    msg.append(f"TICK {TICK_FROM}起：完整 {full} 天，有缺 {len(cov)} 天")
    i = 0
    while i < len(cov):  # 相鄰日期缺同一批檔案者合併為一行
        j = i
        whole = lambda k: cov[k][1] == cov[k][2]
        while j + 1 < len(cov) and ((whole(i) and whole(j + 1)) or
                                    (not whole(i) and cov[j + 1][3] == cov[i][3])):
            j += 1
        d, m, n, miss = cov[i]
        rng = f"{cov[i][0]}~{cov[j][0]}（{j-i+1}天）" if j > i else str(d)
        if m == n:
            msg.append(f"　{rng} 整天未下載")
        else:
            msg.append(f"　{rng} 缺 {m}/{n} 檔：" + "、".join(miss[:10]) + ("…" if m > 10 else ""))
        i = j + 1
    open(REPORT, "w").write("\n".join(msg[:3] + prob + msg[3 + len(grp):]) + "\n")
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
    keys = [f"{k}/{c}/{d}" for k, c, d, p in new] + [f"day/{c}/{r['date']}" for c, rows in dnew.items() for r in rows]
    json.dump({"name": name, "parts": parts, "keys": keys}, open(PENDING, "w"))
    push_pending(t0)


if __name__ == "__main__":
    main()
