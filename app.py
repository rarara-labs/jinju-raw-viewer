import streamlit as st
import pandas as pd
import base64
import json
import io
import requests
from datetime import date, timedelta

# ── GitHub 설정 ──
DATA_URL      = "https://raw.githubusercontent.com/ons-jinju/260527_-/main/26%EB%85%84_%EC%A7%84%EC%A3%BC%ED%92%88%EC%A7%88%EA%B0%9C%EC%84%A0%ED%8C%80_%EA%B3%A0%EC%9E%A5_RAW_DATA.xlsx"
_GITHUB_REPO  = "ons-jinju/260527_-"
_HIST_FILE    = "alarm_history.json"

st.set_page_config(
    page_title="RAW 알람 이력",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
html,body,[class*="css"]{font-family:'Noto Sans KR',sans-serif;}
.stTabs [data-baseweb="tab-list"]{gap:1px;}
.stTabs [data-baseweb="tab"]{padding:6px 14px;font-size:13px;}
.block-container{padding-top:2rem!important;}
.rep-card{
  border-left:4px solid #f03e3e;
  border-radius:6px;padding:8px 12px;margin-bottom:6px;
  background:rgba(240,62,62,.05);line-height:1.5;
}
@media(max-width:768px){
  .block-container{padding:.4rem .5rem!important;padding-top:2.5rem!important;}
}
</style>
""", unsafe_allow_html=True)


# ════════════════════════════════════════════
#  유틸
# ════════════════════════════════════════════
def safe(val):
    if val is None or (isinstance(val, float) and pd.isna(val)): return ''
    return str(val).strip()

def _gh_headers():
    token = st.secrets.get("GITHUB_TOKEN", "")
    return {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}

@st.cache_data(ttl=1800)
def load_alarm_history():
    """GitHub에서 알람 히스토리 로드"""
    try:
        url = f"https://api.github.com/repos/{_GITHUB_REPO}/contents/{_HIST_FILE}"
        r = requests.get(url, headers=_gh_headers(), timeout=10)
        if r.status_code == 200:
            content = base64.b64decode(r.json()['content']).decode('utf-8')
            return json.loads(content)
    except Exception:
        pass
    return {}


# ════════════════════════════════════════════
#  데이터 로딩
# ════════════════════════════════════════════
@st.cache_data(ttl=3600)
def load_data(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    xl = pd.ExcelFile(io.BytesIO(r.content))
    df = pd.read_excel(xl, sheet_name='5G_LTE OOS_진주')
    df.columns = df.columns.str.strip()
    df['본부'] = pd.to_datetime(df['본부'], errors='coerce')
    df['발생시각_dt'] = pd.to_datetime(df['발생시각'], errors='coerce')
    df = df.drop_duplicates(subset=['Port','발생시각'], keep='last').copy()
    return df

def enrich(df, hist):
    """복구여부·다발횟수·알람명 컬럼 추가"""
    df = df.copy()
    today_ports = set(
        df[df['본부'].dt.date == date.today()]['Port'].dropna().astype(str)
    )
    port_latest = df.groupby('Port')['발생시각_dt'].max()
    port_count  = df.groupby('Port')['발생시각'].nunique()

    def get_status(row):
        port = str(row['Port']) if pd.notna(row['Port']) else ''
        if port not in today_ports: return '복구'
        latest = port_latest.get(port)
        if pd.notna(latest) and row['발생시각_dt'] == latest: return '미복구'
        return '복구'

    df['_복구여부']  = df.apply(get_status, axis=1)
    df['_다발횟수']  = df['Port'].map(port_count).fillna(1).astype(int)

    def get_alarm(row):
        port = safe(row.get('Port', ''))
        dk   = ''
        try: dk = pd.Timestamp(row['본부']).strftime('%Y-%m-%d')
        except: pass
        if dk and hist.get(dk, {}).get(port): return hist[dk][port]
        if hist.get('_ports', {}).get(port):  return hist['_ports'][port]
        lv = safe(row.get('5G Link 알람', ''))
        if lv and lv not in ('nan','Service Unavailable'):
            return lv.split(':',1)[-1].strip() if ':' in lv else lv
        sv = safe(row.get('세부알람', ''))
        if sv and sv not in ('nan','Service Unavailable'): return sv
        return ''

    df['알람'] = df.apply(get_alarm, axis=1)
    return df.sort_values('발생시각_dt', ascending=False).drop(columns=['발생시각_dt'])


# ════════════════════════════════════════════
#  헤더
# ════════════════════════════════════════════
st.markdown("##### 🏢 진주품질개선팀")
st.markdown("## 📋 RAW 알람 이력 뷰어")

col_r, col_b = st.columns([6,1])
with col_b:
    if st.button("🔄 새로고침"):
        st.cache_data.clear()
        st.rerun()

with st.spinner("데이터 로딩 중..."):
    try:
        df_raw = load_data(DATA_URL)
        hist   = load_alarm_history()
        df_all = enrich(df_raw, hist)
    except Exception as e:
        st.error(f"❌ 로드 실패: {e}")
        st.stop()

# 날짜 범위
all_dates = sorted(df_all['본부'].dropna().dt.date.unique())
min_d, max_d = (all_dates[0], all_dates[-1]) if all_dates else (date.today(), date.today())

st.divider()

# ════════════════════════════════════════════
#  필터 패널
# ════════════════════════════════════════════
fc1, fc2, fc3, fc4 = st.columns([2,2,2,2])
date_from = fc1.date_input("시작일", value=max_d - timedelta(days=30),
                            min_value=min_d, max_value=max_d, key="df")
date_to   = fc2.date_input("종료일", value=max_d,
                            min_value=min_d, max_value=max_d, key="dt")
status_f  = fc3.selectbox("복구여부", ['전체','미복구','복구'], key="sf")
search    = fc4.text_input("검색", placeholder="🔍 장비명·Port·시군구", label_visibility="collapsed", key="sq")

# 필터 적용
mask = (
    df_all['본부'].dt.date.between(date_from, date_to)
)
df_f = df_all[mask].copy()
if status_f != '전체':
    df_f = df_f[df_f['_복구여부'] == status_f]
if search:
    sq = search.lower()
    df_f = df_f[df_f[['장비명','Port','시군구']].apply(
        lambda r: sq in str(r).lower(), axis=1)]

st.caption(f"📊 조회 결과: **{len(df_f)}건** ({date_from} ~ {date_to})")

tab1, tab2 = st.tabs(["📜 알람 이력", "🔁 중복고장"])


# ══════════════════════════════════════════════════
#  TAB1  알람 이력
# ══════════════════════════════════════════════════
with tab1:
    if df_f.empty:
        st.info("해당 기간 데이터가 없습니다.")
    else:
        # 표시 컬럼
        want = ['발생시각','장비명','Port','시스템','시군구',
                '고장구분','고장구분(중분류)','_복구여부','알람','복구/미복구 상세내역']
        show_cols = [c for c in want if c in df_f.columns]

        def row_style(row):
            if row.get('_복구여부') == '미복구':
                return ['background:rgba(240,62,62,.07)'] * len(row)
            return [''] * len(row)

        st.dataframe(
            df_f[show_cols].rename(columns={'_복구여부':'복구여부'}),
            use_container_width=True,
            height=520,
            hide_index=True
        )

        # 엑셀 다운로드
        buf = io.BytesIO()
        df_f[show_cols].rename(columns={'_복구여부':'복구여부'}).to_excel(
            buf, index=False, engine='openpyxl')
        buf.seek(0)
        st.download_button(
            label=f"⬇️ 엑셀 다운로드 ({date_from}~{date_to}, {len(df_f)}건)",
            data=buf,
            file_name=f"알람이력_{date_from}_{date_to}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )


# ══════════════════════════════════════════════════
#  TAB2  중복고장
# ══════════════════════════════════════════════════
with tab2:
    # 기간 내 Port별 발생 횟수 재계산
    rep_cnt = df_f.groupby('Port')['발생시각'].nunique().reset_index()
    rep_cnt.columns = ['Port', '발생횟수']

    min_cnt = st.slider("최소 반복 횟수", min_value=2, max_value=10, value=2, key="rmin")
    rep_cnt = rep_cnt[rep_cnt['발생횟수'] >= min_cnt].sort_values('발생횟수', ascending=False)

    if rep_cnt.empty:
        st.info(f"해당 기간 {min_cnt}회 이상 중복고장 없음")
    else:
        st.caption(f"🔁 중복고장 **{len(rep_cnt)}개** 포트 ({min_cnt}회 이상)")

        # 포트별 상세
        for _, pr in rep_cnt.iterrows():
            port = pr['Port']
            cnt  = pr['발생횟수']
            rows = df_f[df_f['Port'] == port].sort_values('발생시각', ascending=False)
            nm   = safe(rows.iloc[0].get('장비명','')) if not rows.empty else port
            sys_ = safe(rows.iloc[0].get('시스템','')) if not rows.empty else ''
            sg   = safe(rows.iloc[0].get('시군구',''))  if not rows.empty else ''
            alm  = safe(rows.iloc[0].get('알람',''))    if not rows.empty else ''
            sts  = rows.iloc[0].get('_복구여부','')     if not rows.empty else ''
            sts_color = '#f03e3e' if sts == '미복구' else '#2f9e44'

            with st.expander(
                f"🔁 {nm}  |  {cnt}회  |  {sys_} {sg}  "
                f"{'🔴 미복구' if sts=='미복구' else '🟢 복구'}",
                expanded=False
            ):
                # 발생 이력 테이블
                detail_cols = [c for c in ['발생시각','알람','_복구여부','복구/미복구 상세내역'] if c in rows.columns]
                st.dataframe(
                    rows[detail_cols].rename(columns={'_복구여부':'복구여부'}),
                    use_container_width=True,
                    hide_index=True
                )

        # 중복고장 엑셀 다운로드
        rep_detail = df_f[df_f['Port'].isin(rep_cnt['Port'])]
        want_r = ['발생시각','장비명','Port','시스템','시군구','알람','_복구여부','복구/미복구 상세내역']
        show_r = [c for c in want_r if c in rep_detail.columns]

        buf2 = io.BytesIO()
        rep_detail[show_r].rename(columns={'_복구여부':'복구여부'}).to_excel(
            buf2, index=False, engine='openpyxl')
        buf2.seek(0)
        st.download_button(
            label=f"⬇️ 중복고장 엑셀 다운로드 ({len(rep_cnt)}개 포트)",
            data=buf2,
            file_name=f"중복고장_{date_from}_{date_to}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
