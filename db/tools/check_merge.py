import os,sys,glob,json
import numpy as np,pandas as pd
sys.path.insert(0,'tools');from sdb import SDB
db,bak,inx=sys.argv[1:4]
def blocks(d,kind):
    out={}
    for p in glob.glob(f'{d}/{kind}/*.sdb'):
        s=SDB(p)
        with open(p,'rb') as f:
            for b in s.blocks:
                f.seek(s.start+b['o']);out[(b['k'],b.get('day'),os.path.basename(p) if kind=='m1' else '')]=(b['r'],f.read(b['l']))
    return out
# 1) 舊 TICK 區塊位元組不變
A=blocks(bak,'tick');B=blocks(db,'tick')
chg=[k for k in A if A[k]!=B.get(k)];print('舊TICK區塊',len(A),'變動',len(chg),'新庫區塊',len(B))
# 2) inbox 每檔列數
bad=[];n=0
tk={(k[0],k[1]):v[0] for k,v in B.items()}
m1rows={}
for p in glob.glob(f'{db}/m1/*.sdb'):
    for b,d in SDB(p).get(as_df=False):
        u,c=np.unique(d['date'],return_counts=True)
        for a,m in zip(u,c): m1rows[(b['k'],int(a))]=int(m)
for f in glob.glob(f'{inx}/sj_data/*/*.csv'):
    fn=os.path.basename(f);k=fn.split('_')[0];c=f.split('/')[-2];d=int(fn[-12:-4]);r=sum(1 for _ in open(f))-1;n+=1
    got=tk.get((c,d)) if k=='tick' else m1rows.get((c,d))
    if got!=r: bad.append((k,c,d,r,got))
print('inbox檔',n,'列數不符',len(bad),bad[:5])
# 3) TICK量(到13:30) vs 1分K量
m1v={}
for p in glob.glob(f'{db}/m1/m1_2026*.sdb'):
    df=SDB(p).get();g=df.groupby(['code','date']).volume.sum()
    m1v.update({(c,int(d)):v for (c,d),v in g.items()})
res=[]
for p in sorted(glob.glob(f'{db}/tick/*.sdb')):
    for b,d in SDB(p).get(as_df=False):
        if b['k'] in('001','101'):continue
        v=int(d['volume'][d['t']<14*3600*1e6].sum());mv=m1v.get((b['k'],b['day']))
        res.append((b['k'],b['day'],v,mv))
r=pd.DataFrame(res,columns=['code','date','tv','mv'])
nom=r.mv.isna();ok=(r.tv==r.mv)
print('TICK區塊',len(r),'無1分K',int(nom.sum()),'量相等',int(ok.sum()),'不等',int((~ok&~nom).sum()))
x=r[~ok&~nom].copy();x['diff']=x.tv-x.mv;x['pct']=(x.tv/x.mv-1)*100
x.to_csv('tick_mismatch.csv',index=False)
print(x.groupby('date').size().sort_values(ascending=False).head(10))
print(x.sort_values('pct',key=abs,ascending=False).head(15).to_string())
print(r[nom].head())
