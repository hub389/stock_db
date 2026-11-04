# stock_db（2026-11-04 起改為 SDB1 分析專用格式）

舊的分割 zip／tar.gz 包已全部轉入 `db/`，並逐筆核對一致後刪除。

## 結構
| 路徑 | 內容 |
|---|---|
| db/manifest.json | 資料目錄：交易日曆、每檔每日 1分K／TICK 有無（位元字串）、日K期間、檔案清單與檢查碼 |
| db/daily.sdb | 日K：384檔＋IX0001加權、IX0043櫃買（day_src 見 manifest；多為還原權值） |
| db/feat.sdb | 每日特徵摘要（由1分K算出）：開高低收量、前收、開盤後5/15/30/60分收盤與累積量、09:30前高低、高低點時間 |
| db/m1/m1_YYYYMM.sdb | 1分K，每月一檔，每檔股票一個區塊（含 001 加權、101 櫃買） |
| db/tick/tick_起-迄.sdb | TICK，每檔 < 90MB，每檔股票每日一個區塊 |
| db/txf.sdb | 台指期日盤1分K（已清理） |
| db/excl/ | 剔除43檔的日K與1分K |
| db/misc/ | 量比倍數庫等其他檔案 |
| db/tools/ | sdb.py（Python 讀寫）、sdb.js（App 讀取）、merge.py（合併）、sdb_up.py（手機補檔上傳） |
| inbox/ | 手機上傳、尚未合併的增量包 |

## 取用（只抓需要的部分）
```
git clone --depth 1 --filter=blob:none --sparse https://github.com/hub389/stock_db.git && cd stock_db && git sparse-checkout set --no-cone '/db/*.sdb' '/db/*.json' '/db/tools/' '/inbox/'
```
需要 1分K／TICK 時再加：`git sparse-checkout add '/db/m1/'`（或指定月份檔）

## 讀取
Python（只需 numpy、pandas）：
```
import sys; sys.path.insert(0,'db/tools'); from sdb import SDB
SDB('db/m1/m1_202610.sdb').get('3037')          # 1分K（t=分鐘，541=09:01）
SDB('db/tick/tick_20261023-20261030.sdb').get('3037', 20261030)   # TICK（t=當日微秒）
SDB('db/daily.sdb').get()                        # 全部日K
```
App（JS，免外掛）：`await (await SDB.open(file)).get('3037', 20261030)`

## 格式 SDB1
`"SDB1"` ＋ uint32 表頭長度 ＋ JSON 表頭 ＋ 各區塊（zlib）。價格以整數×100存放；TICK 時間差分存放。詳見 db/tools/sdb.py 說明。
