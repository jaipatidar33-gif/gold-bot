import requests, time, os, json, base64
import pandas as pd
from datetime import datetime, timezone, timedelta

TG = os.environ.get("TG_TOKEN")
CI = os.environ.get("TG_CHAT")
DK = os.environ.get("TD_KEY")
GH_TOKEN = os.environ.get("GITHUB_TOKEN")
GH_REPO = os.environ.get("GITHUB_REPOSITORY")
STATE_FILE = "state.json"


def load_state():
    try:
        with open(STATE_FILE, "r") as f: return json.load(f)
    except:
        return {"position":None,"last_session":"","session_open_time":"","session_high":None,"session_low":None,
                "session_h":{},"session_l":{},"prev_h":{},"prev_l":{},"session_open_price":{},"session_range":{},
                "exhaust_alerted":"","last_hold_msg":"","last_signal_price":0,"last_signal_time":"","flip_count":0,
                "last_sl_time":"","daily_loss":0,"wins":0,"losses":0,"today_date":"","session_alerted":"",
                "open_alerted":"","close_alerted":"","sweep_done":"","neutral_alerted":"","last_1m_check":"",
                "last_big_candle":"","cache":{},"loss_streak":0}


def save_state(s):
    try:
        with open(STATE_FILE,"w") as f: json.dump(s,f,indent=2,default=str)
    except Exception as e: print("State fail:"+str(e))
    if not GH_TOKEN or not GH_REPO: return
    api="https://api.github.com/repos/"+GH_REPO+"/contents/"+STATE_FILE
    h={"Authorization":"token "+GH_TOKEN}
    try:
        r=requests.get(api,headers=h)
        sha=r.json().get("sha") if r.status_code==200 else None
        c=base64.b64encode(json.dumps(s,indent=2,default=str).encode()).decode()
        d={"message":"state update","content":c}
        if sha: d["sha"]=sha
        requests.put(api,headers=h,json=d,timeout=30)
    except Exception as e: print("State push fail:"+str(e))


def send(m):
    try:
        requests.post("https://api.telegram.org/bot"+TG+"/sendMessage",
                      data={"chat_id":CI,"text":m,"parse_mode":"HTML"},timeout=30)
    except Exception as e: print("TG fail:"+str(e))


def to_ist(d): return d+timedelta(hours=5,minutes=30)

def fmt_t(d):
    i=to_ist(d); h,m=i.hour,i.minute; a="AM" if h<12 else "PM"; h12=h%12 or 12
    return str(h12)+":"+str(m).zfill(2)+" "+a+" IST"

def fmt_d(d): return to_ist(d).strftime("%d-%m-%Y")


def get_dst():
    try:
        n=pd.Timestamp.now(tz='UTC')
        return (n.tz_convert('America/New_York').dst().total_seconds()>0,
                n.tz_convert('Europe/London').dst().total_seconds()>0)
    except: return False,False

def is_weekend(): return datetime.now(timezone.utc).weekday() in [5,6]

def is_holiday():
    n=datetime.now(timezone.utc)
    for m,d in [(1,1),(1,20),(2,17),(5,26),(7,4),(9,1),(11,27),(12,25)]:
        if n.month==m and n.day==d: return True
    return False

def is_market_open(): return not (is_weekend() or is_holiday())


def get_session():
    h=datetime.now(timezone.utc).hour
    ny,ld=get_dst()
    lo=7 if ld else 8; lc=16 if ld else 17; no=12 if ny else 13; nc=21 if ny else 22
    if nc<=h or h<3: return "SYDNEY"
    if 3<=h<9: return "TOKYO"
    if 9<=h<no: return "LONDON"
    if no<=h<lc: return "NY_OVERLAP"
    if lc<=h<nc: return "NEWYORK"
    return "SYDNEY"

def is_active(s): return s in ["TOKYO","LONDON","NY_OVERLAP","NEWYORK"]

def get_seg(df,s):
    t=df["dt"].iloc[-1].date()
    ny,ld=get_dst()
    lo=7 if ld else 8; lc=16 if ld else 17; no=12 if ny else 13; nc=21 if ny else 22
    if s=="SYDNEY": return df[(df["dt"].dt.date==t)&((df["dt"].dt.hour>=nc)|(df["dt"].dt.hour<3))]
    if s=="TOKYO": return df[(df["dt"].dt.date==t)&(df["dt"].dt.hour>=3)&(df["dt"].dt.hour<9)]
    if s=="LONDON": return df[(df["dt"].dt.date==t)&(df["dt"].dt.hour>=9)&(df["dt"].dt.hour<no)]
    if s=="NY_OVERLAP": return df[(df["dt"].dt.date==t)&(df["dt"].dt.hour>=no)&(df["dt"].dt.hour<lc)]
    if s=="NEWYORK": return df[(df["dt"].dt.date==t)&(df["dt"].dt.hour>=lc)&(df["dt"].dt.hour<nc)]
    return df.tail(50)

def get_prev_sess(s):
    o=["SYDNEY","TOKYO","LONDON","NY_OVERLAP","NEWYORK"]
    i=o.index(s) if s in o else 0
    return o[(i-1)%len(o)]

def is_session_transition(old_s, new_s):
    return bool(old_s) and old_s != new_s

def is_ny_close():
    n=datetime.now(timezone.utc); ny,_=get_dst(); nh=21 if ny else 22
    return n.hour==nh and n.minute<10

def is_fri_close():
    n=datetime.now(timezone.utc)
    return n.weekday()==4 and n.hour==20 and n.minute<10

def get_kz():
    h=datetime.now(timezone.utc).hour; ny,ld=get_dst()
    lo=7 if ld else 8; no=12 if ny else 13
    if lo<=h<lo+1: return "London KZ"
    if no<=h<no+1: return "NY KZ"
    return None

def is_silver_bullet():
    ny,_=get_dst(); sb=14 if ny else 15
    return datetime.now(timezone.utc).hour==sb


def is_news():
    n=datetime.now(timezone.utc); h,m,dow=n.hour,n.minute,n.weekday()
    ny,_=get_dst(); nh=12 if ny else 13; fh=18 if ny else 19
    if dow==4 and h==nh and 25<=m<=40: return "NFP"
    if dow in [0,1,2,3,4] and h==fh and 55<=m<=65: return "FED"
    if dow in [0,1,2,3,4] and h==nh and 25<=m<=40: return "CPI"
    return None

def is_pre_news():
    n=datetime.now(timezone.utc); h,m,dow=n.hour,n.minute,n.weekday()
    ny,_=get_dst(); nh=12 if ny else 13; fh=18 if ny else 19
    if dow==4 and h==nh and 10<=m<=24: return "NFP in "+str(25-m)+" min"
    if dow in [0,1,2,3,4] and h==fh and 40<=m<=54: return "FED in "+str(55-m)+" min"
    if dow in [0,1,2,3,4] and h==nh and 10<=m<=24: return "CPI in "+str(25-m)+" min"
    return None

def news_day():
    n=datetime.now(timezone.utc); dow,d=n.weekday(),n.day; w=[]
    if dow==4 and 1<=d<=7: w.append("NFP Friday")
    if dow==2 and 10<=d<=14: w.append("CPI Day")
    if dow==3 and 15<=d<=21: w.append("FOMC Possible")
    return w


def fetch(i,s):
    u="https://api.twelvedata.com/time_series"
    p={"symbol":"XAU/USD","interval":i,"outputsize":s,"apikey":DK}
    for _ in range(3):
        try:
            r=requests.get(u,params=p,timeout=20).json()
            if "values" in r:
                d=pd.DataFrame(r["values"])
                d["dt"]=pd.to_datetime(d["datetime"])
                for c in ["open","high","low","close"]: d[c]=d[c].astype(float)
                return d.sort_values("dt").reset_index(drop=True)
        except: time.sleep(2)
    return None

def fetch_live():
    try:
        r=requests.get("https://api.twelvedata.com/price",
                       params={"symbol":"XAU/USD","apikey":DK},timeout=8).json()
        if "price" in r: return float(r["price"])
    except: pass
    return None


def ema(a,p):
    k=2.0/(p+1); e=a[0]
    for x in a[1:]: e=x*k+e*(1-k)
    return e

def sma(a,p):
    if len(a)<p: return a[-1]
    return sum(a[-p:])/p

def rsi(a,p=14):
    if len(a)<p+1: return 50
    g=l=0
    for i in range(len(a)-p,len(a)):
        d=a[i]-a[i-1]
        if d>0: g+=d
        else: l-=d
    if l==0: return 100
    return 100-100/(1+(g/p)/(l/p))

def atr(df,p=14):
    if len(df)<p+1: return 0
    tr=[]
    for i in range(len(df)-p,len(df)):
        h,l,pc=df["high"].iloc[i],df["low"].iloc[i],df["close"].iloc[i-1]
        tr.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sum(tr)/p

def swings(df,w=3):
    H,L=[],[]
    for i in range(w,len(df)-w):
        if df["high"].iloc[i]==df["high"].iloc[i-w:i+w+1].max(): H.append(df["high"].iloc[i])
        if df["low"].iloc[i]==df["low"].iloc[i-w:i+w+1].min(): L.append(df["low"].iloc[i])
    return H,L

def find_fvg(df):
    o=[]
    for i in range(2,len(df)):
        c1h,c1l=df["high"].iloc[i-2],df["low"].iloc[i-2]
        c3h,c3l=df["high"].iloc[i],df["low"].iloc[i]
        if c1h<c3l: o.append({"t":"B","top":round(c3l,2),"bot":round(c1h,2),"ce":round((c1h+c3l)/2,2)})
        if c1l>c3h: o.append({"t":"S","top":round(c1l,2),"bot":round(c3h,2),"ce":round((c1l+c3h)/2,2)})
    return o

def find_ob(df):
    b=s=None
    for i in range(len(df)-3,max(len(df)-30,0),-1):
        c=df.iloc[i]; n1=df.iloc[i+1]; n2=df.iloc[i+2]
        if b is None and c["close"]<c["open"] and n1["close"]>n1["open"] and n2["close"]>n2["open"]:
            b={"top":round(c["open"],2),"bot":round(c["low"],2)}
        if s is None and c["close"]>c["open"] and n1["close"]<n1["open"] and n2["close"]<n2["open"]:
            s={"top":round(c["high"],2),"bot":round(c["open"],2)}
    return b,s

def ch_choch(df):
    H,L=swings(df)
    if len(H)<3 or len(L)<3: return None
    if H[-1]>H[-2] and L[-1]>L[-2]: return "BULL"
    if H[-1]<H[-2] and L[-1]<L[-2]: return "BEAR"
    return None

def ch_disp(df,av):
    if len(df)<3 or av==0: return None
    c=df.iloc[-1]; b=abs(c["close"]-c["open"])
    if b>av*1.5: return "BULL" if c["close"]>c["open"] else "BEAR"
    return None

def ch_eq(lv,tol=5):
    if len(lv)<2: return False
    for i in range(len(lv)-1):
        if abs(lv[i]-lv[i+1])<tol: return True
    return False

def ch_adx(df,p=14):
    if len(df)<p*2: return 0
    tr,pl,mi=[],[],[]
    for i in range(len(df)-p*2,len(df)):
        h,l,pc=df["high"].iloc[i],df["low"].iloc[i],df["close"].iloc[i-1]
        ph,pl2=df["high"].iloc[i-1],df["low"].iloc[i-1]
        tr.append(max(h-l,abs(h-pc),abs(l-pc)))
        up,dn=h-ph,pl2-l
        pl.append(up if up>dn and up>0 else 0)
        mi.append(dn if dn>up and dn>0 else 0)
    a=sum(tr[-p:])/p
    if a==0: return 0
    pdi=100*(sum(pl[-p:])/p)/a; mdi=100*(sum(mi[-p:])/p)/a
    if pdi+mdi==0: return 0
    return 100*abs(pdi-mdi)/(pdi+mdi)

def ch_mom(m5):
    if len(m5)<4: return None,0
    r=(m5["high"]-m5["low"]).tail(20); av=r.mean()
    if av==0: return None,0
    l3=m5.tail(3); mv=abs(l3["close"].iloc[-1]-l3["open"].iloc[0]); sp=mv/av
    d="BULL" if l3["close"].iloc[-1]>l3["open"].iloc[-1] else "BEAR"
    if sp>1.2: return "FAST_"+d,sp
    if sp>0.7: return "MED_"+d,sp
    return "SLOW",sp

def ch_pa(m5):
    if len(m5)<2: return []
    s=[]; c1=m5.iloc[-1]; c2=m5.iloc[-2]
    b=abs(c1["close"]-c1["open"]); uw=c1["high"]-max(c1["close"],c1["open"]); dw=min(c1["close"],c1["open"])-c1["low"]
    if b==0: b=0.01
    if dw>b*2.5 and uw<b*0.5: s.append("Bull Rejection")
    if uw>b*2.5 and dw<b*0.5: s.append("Bear Rejection")
    if c1["close"]>c1["open"] and b>(c1["high"]-c1["low"])*0.7: s.append("Strong Bull")
    if c1["close"]<c1["open"] and b>(c1["high"]-c1["low"])*0.7: s.append("Strong Bear")
    if c2["close"]<c2["open"] and c1["close"]>c1["open"] and c1["close"]>c2["open"]: s.append("Bull Engulf")
    if c2["close"]>c2["open"] and c1["close"]<c1["open"] and c1["close"]<c2["open"]: s.append("Bear Engulf")
    return s

def vol_spike(m5):
    r=(m5["high"]-m5["low"]).tail(20); a=r.mean()
    if a==0: return False
    return (m5["high"].iloc[-1]-m5["low"].iloc[-1])>a*1.3

def sess_hl(df,s):
    seg=get_seg(df,s)
    if len(seg)==0: return None,None
    return round(seg["high"].max(),2),round(seg["low"].min(),2)

def calc_adr(daily):
    if len(daily)<14: return 250
    return (daily.tail(14)["high"]-daily.tail(14)["low"]).mean()

def pip_cycle(s,adr):
    p={"SYDNEY":0.12,"TOKYO":0.18,"LONDON":0.45,"NY_OVERLAP":0.50,"NEWYORK":0.45}
    return round(adr*p.get(s,0.20))

def all_sess_lv(df):
    o={}
    for s in ["SYDNEY","TOKYO","LONDON","NY_OVERLAP","NEWYORK"]:
        h,l=sess_hl(df,s)
        if h and l: o[s]={"h":h,"l":l}
    return o

def liq_sweep(m5,side):
    if len(m5)<5: return False
    H,L=swings(m5,w=2)
    if len(H)<2 or len(L)<2: return False
    rh,rl=H[-1],L[-1]; c1=m5.iloc[-1]; c2=m5.iloc[-2]
    if side=="LONG" and c2["low"]<rl-3 and c1["close"]>rl: return True
    if side=="SHORT" and c2["high"]>rh+3 and c1["close"]<rh: return True
    return False

def liq_magnet(h1,m15,cur):
    H,L=swings(h1)
    b=sorted([x for x in H if x>cur])[:5]
    s=sorted([x for x in L if x<cur],reverse=True)[:5]
    return {"nB":round(b[0],2) if b else None,"nS":round(s[0],2) if s else None,
            "mB":round(b[1],2) if len(b)>1 else None,"mS":round(s[1],2) if len(s)>1 else None,
            "fB":round(b[-1],2) if len(b)>1 else None,"fS":round(s[-1],2) if len(s)>1 else None}

def pwh_pwl(d):
    if len(d)<14: return None,None
    lw=d.iloc[-14:-7]
    if len(lw)==0: return None,None
    return round(lw["high"].max(),2),round(lw["low"].min(),2)

def ch_1m(m1):
    if m1 is None or len(m1)<5: return None
    r=(m1["high"]-m1["low"]).tail(20); a=r.mean()
    if a==0: return None
    c=m1.iloc[-1]; cr=c["high"]-c["low"]; ratio=cr/a
    b=abs(c["close"]-c["open"]); bp=(b/cr*100) if cr>0 else 0
    dir="BULL" if c["close"]>c["open"] else "BEAR"
    if ratio>=2.5 and bp>=60:
        return {"ratio":round(ratio,2),"range":round(cr,2),"body":round(bp,1),"dir":dir}
    return None

def cnt_1m(m1,dir):
    if m1 is None or len(m1)<3: return 0
    c=0
    for i in range(len(m1)-1,max(len(m1)-4,-1),-1):
        cd=m1.iloc[i]
        if dir=="BEAR" and cd["close"]<cd["open"]: c+=1
        elif dir=="BULL" and cd["close"]>cd["open"]: c+=1
        else: break
    return c


def hold_break(state,h1,m15,m5,cur):
    p=state.get("position")
    if not p: return False,"",""
    side,e,sl=p["side"],p["entry"],p["sl"]
    sd=abs(sl-e)
    loss=(e-cur) if side=="LONG" else (cur-e)
    if loss<=0: return False,"",""
    prog=loss/sd if sd>0 else 0
    score=0; r=[]
    c15=ch_choch(m15); c1h=ch_choch(h1)
    if side=="LONG" and c15=="BEAR": score+=2; r.append("M15 CHoCH Bear")
    if side=="SHORT" and c15=="BULL": score+=2; r.append("M15 CHoCH Bull")
    if side=="LONG" and c1h=="BEAR": score+=2; r.append("H1 CHoCH Bear")
    if side=="SHORT" and c1h=="BULL": score+=2; r.append("H1 CHoCH Bull")
    if liq_sweep(m5,side): score+=2; r.append("Liq Sweep")
    if vol_spike(m5): score+=1; r.append("Vol Spike")
    if prog>=0.75: score+=2; r.append("75% Loss")
    elif prog>=0.5: score+=1; r.append("50% Loss")
    pa=ch_pa(m5)
    if side=="LONG" and any("Bear" in x for x in pa): score+=1; r.append("Bear PA")
    if side=="SHORT" and any("Bull" in x for x in pa): score+=1; r.append("Bull PA")
    if score>=4: return True," | ".join(r),"EXIT_AND_REVERSE"
    if score>=3: return True," | ".join(r),"EXIT_NOW"
    if score>=2: return True," | ".join(r),"WARNING"
    return False,"",""


def flip_cycle(state,cur,h1,m15,m5):
    if state.get("flip_count",0)>=4: return None
    adx=ch_adx(h1); p=state.get("position")
    if not p: return None
    side,e,tp1,sl=p["side"],p["entry"],p["tp1"],p["sl"]
    sd=abs(sl-e)
    pnl=(cur-e) if side=="LONG" else (e-cur)
    pl=((e-cur)/sd) if side=="LONG" else ((cur-e)/sd) if sd>0 else 0
    hit=(cur>=tp1) if side=="LONG" else (cur<=tp1)
    if hit: return {"act":"TP_FLIP","rev":"SHORT" if side=="LONG" else "LONG","r":"Target hit"}
    if pl>=0.75: return {"act":"SL_FLIP","rev":"SHORT" if side=="LONG" else "LONG","r":"75% loss"}
    c15=ch_choch(m15); c1h=ch_choch(h1)
    rev=False; r=[]
    if side=="LONG" and c15=="BEAR": rev=True; r.append("M15 Bear")
    if side=="SHORT" and c15=="BULL": rev=True; r.append("M15 Bull")
    if side=="LONG" and c1h=="BEAR": rev=True; r.append("H1 Bear")
    if side=="SHORT" and c1h=="BULL": rev=True; r.append("H1 Bull")
    if adx>30:
        if side=="LONG" and c1h=="BULL": return None
        if side=="SHORT" and c1h=="BEAR": return None
    if rev: return {"act":"TREND_FLIP","rev":"SHORT" if side=="LONG" else "LONG","r":" | ".join(r)}
    op=p.get("opened_at","")
    if op:
        try:
            od=datetime.strptime(op,"%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
            age=(datetime.now(timezone.utc)-od).total_seconds()/60
            if age>60 and pnl<5: return {"act":"TIME_FLIP","rev":"SHORT" if side=="LONG" else "LONG","r":"60min no profit"}
        except: pass
    return None

def do_flip(state,fi,cur,now):
    rev=fi["rev"]
    if rev=="LONG": sl,tp1,tp2,tp3=cur-20,cur+20,cur+30,cur+40
    else: sl,tp1,tp2,tp3=cur+20,cur-20,cur-30,cur-40
    state["position"]={"side":rev,"entry":cur,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,
                       "tp_hits":[],"warn_hits":[],"opened_at":now}
    state["flip_count"]=state.get("flip_count",0)+1
    return state


def chk_pos(state,cur,now):
    p=state.get("position")
    if not p: return state,None
    side,e,sl=p["side"],p["entry"],p["sl"]
    tp1,tp2,tp3=p["tp1"],p["tp2"],p["tp3"]
    tph=p.get("tp_hits",[]); wh=p.get("warn_hits",[])
    msg=None; sd=abs(sl-e); tr=p.get("trailing_sl")
    if side=="LONG":
        if tr and cur<=tr:
            state["position"]=None; state["wins"]=state.get("wins",0)+1
            return state,"🎯 TRAILING SL - BUY locked at "+str(round(tr,2))
        if cur<=sl:
            state["position"]=None; state["last_sl_time"]=now
            state["losses"]=state.get("losses",0)+1
            state["daily_loss"]=state.get("daily_loss",0)+sd
            return state,"🔴 SL HIT - BUY closed at "+str(round(sl,2))
        adv=e-cur
        if 1 not in wh and adv>=sd*0.25: wh.append(1); msg="⚠️ 25% LOSS: BUY -"+str(round(adv,1))
        if 2 not in wh and adv>=sd*0.5: wh.append(2); msg="⚠️ 50% LOSS: BUY -"+str(round(adv,1))
        if 3 not in wh and adv>=sd*0.75: wh.append(3); msg="🚨 75% LOSS: BUY -"+str(round(adv,1))+" CLOSE NOW"
        if 1 not in tph and cur>=tp1: tph.append(1); p["sl"]=e; msg="✅ TP1 HIT - BUY +20 pips"
        if 2 not in tph and cur>=tp2: tph.append(2); p["trailing_sl"]=tp1; msg="✅ TP2 HIT - BUY +30 pips"
        if 3 not in tph and cur>=tp3:
            tph.append(3); state["position"]=None; state["wins"]=state.get("wins",0)+1
            return state,"✅ TP3 HIT - BUY +40 pips"
    elif side=="SHORT":
        if tr and cur>=tr:
            state["position"]=None; state["wins"]=state.get("wins",0)+1
            return state,"🎯 TRAILING SL - SELL locked at "+str(round(tr,2))
        if cur>=sl:
            state["position"]=None; state["last_sl_time"]=now
            state["losses"]=state.get("losses",0)+1
            state["daily_loss"]=state.get("daily_loss",0)+sd
            return state,"🔴 SL HIT - SELL closed at "+str(round(sl,2))
        adv=cur-e
        if 1 not in wh and adv>=sd*0.25: wh.append(1); msg="⚠️ 25% LOSS: SELL -"+str(round(adv,1))
        if 2 not in wh and adv>=sd*0.5: wh.append(2); msg="⚠️ 50% LOSS: SELL -"+str(round(adv,1))
        if 3 not in wh and adv>=sd*0.75: wh.append(3); msg="🚨 75% LOSS: SELL -"+str(round(adv,1))+" CLOSE NOW"
        if 1 not in tph and cur<=tp1: tph.append(1); p["sl"]=e; msg="✅ TP1 HIT - SELL +20 pips"
        if 2 not in tph and cur<=tp2: tph.append(2); p["trailing_sl"]=tp1; msg="✅ TP2 HIT - SELL +30 pips"
        if 3 not in tph and cur<=tp3:
            tph.append(3); state["position"]=None; state["wins"]=state.get("wins",0)+1
            return state,"✅ TP3 HIT - SELL +40 pips"
    p["tp_hits"]=tph; p["warn_hits"]=wh; state["position"]=p
    return state,msg


def cooldown(state,now):
    ls=state.get("last_sl_time","")
    if not ls: return False
    try:
        ld=datetime.strptime(ls,"%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
        return (now-ld).total_seconds()/60<30
    except: return False


def run():
    state=load_state()
    session=get_session()
    now_utc=datetime.now(timezone.utc)
    now_str=now_utc.strftime("%Y-%m-%d %H:%M UTC")

    print("RUN: " + now_str + " | Session: " + session)

    if not is_market_open(): print("Market closed"); return
    if cooldown(state,now_utc): print("Cooldown"); return
    if state.get("daily_loss",0)>=60: print("Daily loss limit"); return

    today=now_utc.strftime("%Y-%m-%d")
    if state.get("today_date","")!=today:
        state["today_date"]=today; state["daily_loss"]=0

    if is_fri_close():
        k=now_utc.strftime("%Y-%m-%d")
        if state.get("close_alerted","")!=k:
            state["close_alerted"]=k; save_state(state)
            send("🔔 FRIDAY CLOSE\nWeekend aa raha hai\nPositions manage karo")

    if is_ny_close():
        k=now_utc.strftime("%Y-%m-%d")
        if state.get("close_alerted","")!="ny_"+k:
            state["close_alerted"]="ny_"+k; save_state(state)
            send("🔔 NY CLOSE\nMarket close ho raha hai")

    if is_news(): print("News time"); return

    pre=is_pre_news()
    nd=news_day()

    cache=state.get("cache",{})
    now_ts=int(time.time())
    tfs=[("m5","5min",200,300),("m15","15min",200,600),("h1","1h",250,1800),("h4","4h",200,3600),("daily","1day",200,7200)]
    data={}
    for n,i,s,ttl in tfs:
        c=cache.get(n,{})
        if c.get("ts",0)+ttl>now_ts and c.get("data"):
            try:
                d=pd.DataFrame(c["data"])
                if "dt" not in d.columns and "datetime" in d.columns: d["dt"]=pd.to_datetime(d["datetime"])
                for col in ["open","high","low","close"]: d[col]=d[col].astype(float)
                data[n]=d.sort_values("dt").reset_index(drop=True)
            except: data[n]=fetch(i,s)
        else:
            f=fetch(i,s); data[n]=f
            if f is not None:
                try: cache[n]={"ts":now_ts,"data":f.drop(columns=["dt"],errors="ignore").to_dict("records")}
                except: pass
            time.sleep(6)
    state["cache"]=cache
    save_state(state)

    if any(v is None for v in data.values()): print("Fetch failed"); return

    daily,h4,h1=data["daily"],data["h4"],data["h1"]
    m15,m5=data["m15"],data["m5"]
    cur=m5["close"].iloc[-1]
    live=fetch_live()
    if live: cur=live

    print("Live: " + str(round(cur,2)) + " | Session: " + session)

    state,msg=chk_pos(state,cur,now_str)
    if msg: send(msg)

    p=state.get("position")
    if p:
        m1=fetch("1min",50)
        if m1 is not None:
            bc=ch_1m(m1)
            if bc:
                side_txt="BUY" if p["side"]=="LONG" else "SELL"
                against=(p["side"]=="LONG" and bc["dir"]=="BEAR") or (p["side"]=="SHORT" and bc["dir"]=="BULL")
                if against:
                    cnt=cnt_1m(m1,bc["dir"])
                    m="🚨 1M BIG CANDLE - AGAINST "+side_txt+"\n\n"
                    m+="Range: "+str(bc["range"])+" ("+str(bc["ratio"])+"x)\n"
                    m+="Body: "+str(bc["body"])+"%\n"
                    m+="Consecutive: "+str(cnt)+"\n\n"
                    if cnt>=2: m+="Action: REVERSE\nClose "+side_txt
                    else: m+="Action: WATCH\nWait 1 more candle"
                    send(m)

    broken,reason,act=hold_break(state,h1,m15,m5,cur)
    if broken:
        p=state.get("position")
        if p:
            st="BUY" if p["side"]=="LONG" else "SELL"
            if act=="EXIT_AND_REVERSE":
                rt="SELL" if p["side"]=="LONG" else "BUY"
                m="🚨 "+st+" TUT GAYA - REVERSE!\n\n"+reason+"\n\n1. CLOSE "+st+"\n2. Take "+rt+" @ "+str(round(cur,2))
                send(m)
            elif act=="EXIT_NOW": send("⚠️ "+st+" WEAK - EXIT\n\n"+reason)
            elif act=="WARNING": send("⚠️ "+st+" WARNING\n\n"+reason)

    fi=flip_cycle(state,cur,h1,m15,m5)
    if fi:
        os_=state["position"]["side"] if state.get("position") else ""
        state=do_flip(state,fi,cur,now_str); save_state(state)
        ot="BUY" if os_=="LONG" else "SELL"; nt="BUY" if fi["rev"]=="LONG" else "SELL"
        m="🔄 FLIP CYCLE #"+str(state.get("flip_count",1))+"\n\nReason: "+fi["r"]
        m+="\n\n❌ CLOSE "+ot+" @ "+str(round(cur,2))+"\n✅ OPEN "+nt+" @ "+str(round(cur,2))
        send(m); return

    old_s=state.get("last_session","")
    sc=is_session_transition(old_s,session)
    if sc or not state.get("session_open_time"):
        state["session_open_time"]=now_str; state["session_open_price"][session]=cur
        state["session_high"]=cur; state["session_low"]=cur
    if sc: state["flip_count"]=0
    sh=state.get("session_high"); sl=state.get("session_low")
    if sh is None or cur>sh: state["session_high"]=cur
    if sl is None or cur<sl: state["session_low"]=cur
    state["last_session"]=session
    save_state(state)

    if sc:
        prev=get_prev_sess(session)
        lv=all_sess_lv(m5)
        adr=calc_adr(daily)
        pips=pip_cycle(session,adr)
        m="🔔 SESSION CHANGE: "+old_s+" → "+session+"\n\n"
        if prev in lv: m+="Prev "+prev+" H/L: "+str(lv[prev]["h"])+" / "+str(lv[prev]["l"])+"\n"
        m+="Pip Cycle: ~"+str(pips)+" pips\n"
        m+="Time: "+fmt_t(now_utc)
        send(m)

    if p:
        adr=calc_adr(daily)
        pips=pip_cycle(session,adr)
        pnl=(cur-p["entry"]) if p["side"]=="LONG" else (p["entry"]-cur)
        lh=state.get("last_hold_msg","")
        do_hold=True
        if lh:
            try:
                ld=datetime.strptime(lh,"%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
                if (now_utc-ld).total_seconds()/60<30: do_hold=False
            except: pass
        if do_hold:
            state["last_hold_msg"]=now_str; save_state(state)
            st="BUY" if p["side"]=="LONG" else "SELL"
            pnl_txt=("+" if pnl>=0 else "")+str(round(pnl,1))
            m="⏸️ HOLD "+st+"\n\nEntry: "+str(round(p["entry"],2))+"\n"
            m+="Current: "+str(round(cur,2))+"\nP&L: "+pnl_txt+" pips\n"
            m+="SL: "+str(round(p["sl"],2))+"\nTP1: "+str(round(p["tp1"],2))
            m+="\n\nTime: "+fmt_t(now_utc)+"\nSession: "+session
            send(m)

    bull,bear=[],[]
    d_hi,d_lo=daily["high"].max(),daily["low"].min()
    d_mid=(d_hi+d_lo)/2; lv25=d_lo+(d_hi-d_lo)*0.25; lv75=d_lo+(d_hi-d_lo)*0.75
    if cur>d_mid: bull.append("Above Daily 50%")
    else: bear.append("Below Daily 50%")
    if cur<lv25: bull.append("Deep Discount")
    if cur>lv75: bear.append("Deep Premium")
    adr=calc_adr(daily)
    c1=ch_choch(h1)
    if c1=="BULL": bull.append("H1 CHoCH Bull")
    if c1=="BEAR": bear.append("H1 CHoCH Bear")
    c4=ch_choch(h4)
    if c4=="BULL": bull.append("H4 CHoCH Bull")
    if c4=="BEAR": bear.append("H4 CHoCH Bear")
    d=ch_disp(h1,atr(h1))
    if d=="BULL": bull.append("Bull Displacement")
    if d=="BEAR": bear.append("Bear Displacement")
    fvgs=find_fvg(m15)[-15:]
    if any(f["t"]=="B" and abs(cur-f["ce"])<adr*0.3 for f in fvgs): bull.append("Bull FVG")
    if any(f["t"]=="S" and abs(cur-f["ce"])<adr*0.3 for f in fvgs): bear.append("Bear FVG")
    bo,so=find_ob(h1)
    if bo and bo["bot"]-5<=cur<=bo["top"]+5: bull.append("At Bull OB")
    if so and so["bot"]-5<=cur<=so["top"]+5: bear.append("At Bear OB")
    H1,L1=swings(h1)
    if ch_eq(L1): bull.append("Equal Lows")
    if ch_eq(H1): bear.append("Equal Highs")
    rv=rsi(h1["close"].tolist())
    if rv<30: bull.append("RSI Oversold")
    if rv>70: bear.append("RSI Overbought")
    av=ch_adx(h1)
    if av>25:
        if c1=="BULL": bull.append("ADX Strong")
        if c1=="BEAR": bear.append("ADX Strong")
    md,_=ch_mom(m5)
    if md=="FAST_BULL": bull.append("Fast Bull")
    if md=="FAST_BEAR": bear.append("Fast Bear")
    pa=ch_pa(m5)
    for x in pa:
        if "Bull" in x: bull.append(x)
        elif "Bear" in x: bear.append(x)
    pwh,pwl=pwh_pwl(daily)
    if pwh and abs(cur-pwh)<5: bear.append("Near PWH")
    if pwl and abs(cur-pwl)<5: bull.append("Near PWL")

    liq=liq_magnet(h1,m15,cur)

    existing=state.get("position")
    if is_active(session) or session=="SYDNEY":
        bS,sS=len(bull),len(bear)
        conf=max(bS,sS)
        
        print("CHECK: Bull=" + str(bS) + " Bear=" + str(sS) + " Conf=" + str(conf))
        
        if conf<8:
            if bS==sS:
                k=now_utc.strftime("%Y-%m-%d")+"_"+session
                if state.get("neutral_alerted","")!=k:
                    state["neutral_alerted"]=k; save_state(state)
                    t="⚪ NEUTRAL\n\nBull: "+str(bS)+" | Bear: "+str(sS)+"\n"
                    if liq["nB"]: t+="↑ "+str(liq["nB"])+" = BUY\n"
                    if liq["nS"]: t+="↓ "+str(liq["nS"])+" = SELL"
                    send(t)
            return

        action="LONG" if bS>sS else "SHORT"
        lh_aligned=((h1["close"].iloc[-1]>h1["close"].iloc[-2]) == (action=="LONG"))
        if not lh_aligned: print("HTF not aligned"); return
        lp=state.get("last_signal_price",0)
        if lp and abs(cur-lp)>15: print("Late signal drift"); return
        if existing: return
        entry=cur
        av2=atr(h1); av2=max(av2,15)
        if action=="LONG": sl,tp1,tp2,tp3=cur-av2,cur+av2,cur+av2*1.5,cur+av2*2
        else: sl,tp1,tp2,tp3=cur+av2,cur-av2,cur-av2*1.5,cur-av2*2
        state["position"]={"side":action,"entry":entry,"sl":round(sl,2),"tp1":round(tp1,2),
                           "tp2":round(tp2,2),"tp3":round(tp3,2),"tp_hits":[],"warn_hits":[],"opened_at":now_str}
        state["last_signal_price"]=cur; state["last_signal_time"]=now_str
        save_state(state)
        kz=get_kz()
        if action=="LONG": text="🟢 BUY GOLD"
        else: text="🔴 SELL GOLD"
        text+="\n\nEntry: "+str(round(entry,2))+"\nSL: "+str(round(sl,2))
        text+="\n\nTP1: "+str(round(tp1,2))+"\nTP2: "+str(round(tp2,2))+"\nTP3: "+str(round(tp3,2))
        text+="\n\nDate: "+fmt_d(now_utc)+"\nTime: "+fmt_t(now_utc)+"\nSession: "+session
        text+="\nMode: Bull "+str(bS)+" | Bear "+str(sS)
        if liq["nB"]: text+="\nLiq Above: "+str(liq["nB"])
        if liq["nS"]: text+="\nLiq Below: "+str(liq["nS"])
        if kz: text+="\n⚡ "+kz
        if pre: text+="\n\n⚠️ "+pre
        if nd: text+="\n📅 "+", ".join(nd)
        send(text)


if __name__ == "__main__":
    run()
