"""獨立核對：CSV 原檔 vs SDB 主庫（列數全量比對＋隨機抽樣逐值比對）"""
import os,sys,glob,random,json
import pandas as pd,numpy as np
sys.path.insert(0,os.path.dirname(__file__));from sdb import SDB
raw,db=sys.argv[1],sys.argv[2]
man=json.load(open(f'{db}/manifest.json'));cal=man['cal']
# 1) 全量列數
cnt={'m1':0,'tick':0};bad=[]
rows={}
for p in glob.glob(f'{db}/m1/*.sdb'):
    s=SDB(p)
    for b,d in s.get(as_df=False):
        u,n=np.unique(d['date'],return_counts=True)
        for a,m in zip(u,n): rows[('m1',b['k'],int(a))]=int(m)
for p in glob.glob(f'{db}/tick/*.sdb'):
    for b in SDB(p).blocks: rows[('tick',b['k'],b['day'])]=b['r']
seen=set()
for f in glob.glob(f'{raw}/sj_data/*/*.csv'):
    fn=os.path.basename(f);k=fn.split('_')[0];c=f.split('/')[-2];d=int(fn[-12:-4])
    if k not in('m1','tick') or d==20241201: continue
    n=sum(1 for _ in open(f))-1
    seen.add((k,c,d));cnt[k]+=1
    if rows.get((k,c,d))!=n: bad.append((k,c,d,n,rows.get((k,c,d))))
extra=set(rows)-seen
print('檔案數',cnt,'列數不符',len(bad),bad[:5],'庫中多出',len(extra))
# 2) 抽樣逐值
random.seed(7);ks=random.sample(sorted(seen),300);vb=0
for k,c,d in ks:
    a=pd.read_csv(f'{raw}/sj_data/{c}/{k}_{c}_{d}.csv',dtype={'time':str})
    if k=='m1':
        b=SDB(f'{db}/m1/m1_{d//100}.sdb').get(c);b=b[b.date==d].reset_index(drop=True)
        cols=['open','high','low','close','volume','amount']
    else:
        p=[x for x in glob.glob(f'{db}/tick/*.sdb') if int(os.path.basename(x)[5:13])<=d<=int(os.path.basename(x)[14:22])][0]
        b=SDB(p).get(c,d);a=a.rename(columns={'close':'price'})
        cols=['price','volume','bid_price','bid_volume','ask_price','ask_volume','tick_type']
        tt=a.time.str.split('.',n=1,expand=True);fr=(tt[1].fillna('') if tt.shape[1]>1 else '')
        hh=tt[0].str.split(':',expand=True).astype(int)
        us=(hh[0]*3600+hh[1]*60+hh[2])*1000000+fr.str.ljust(6,'0').astype(int)
        if not np.array_equal(us.values,b.t.values): vb+=1;print('時間不符',k,c,d)
    for col in cols:
        if not np.allclose(a[col].values.astype(float),b[col].values.astype(float),rtol=0,atol=1e-9): vb+=1;print('值不符',k,c,d,col)
print('抽樣',len(ks),'檔，逐值不符',vb)
# 3) 日K
dd=SDB(f'{db}/daily.sdb');vb=0
for b in dd.blocks:
    a=pd.read_csv(f'{raw}/day_data/{b["k"]}.csv').sort_values('date').reset_index(drop=True);x=dd.get(b['k'])
    for col in ['date','open','high','low','close','volume','amount']:
        if not np.allclose(a[col].values.astype(float),x[col].values.astype(float),rtol=0,atol=1e-6): vb+=1;print('日K不符',b['k'],col)
print('日K',len(dd.blocks),'檔全量比對，不符',vb)
