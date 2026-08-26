# -*- coding: utf-8 -*-
import streamlit as st
import plotly.graph_objects as go
import plotly.io as pio


def apply_global_theme():
    pio.templates["lunkuo"] = go.layout.Template(layout={
        "font": {"family": "Inter, Microsoft YaHei", "color": "#52657a"},
        "paper_bgcolor": "#ffffff", "plot_bgcolor": "#ffffff",
        "colorway": ["#176eae", "#20b7d3", "#6f63d9", "#16a081", "#ed9b32", "#dc5d72", "#5e86b3"],
        "margin": {"l": 42, "r": 24, "t": 58, "b": 42},
        "hoverlabel": {"bgcolor": "#0d2b4b", "font": {"color": "#ffffff"}},
        "xaxis": {"gridcolor": "#edf2f7", "linecolor": "#dbe6ef", "zerolinecolor": "#dbe6ef"},
        "yaxis": {"gridcolor": "#edf2f7", "linecolor": "#dbe6ef", "zerolinecolor": "#dbe6ef"},
        "legend": {"bgcolor": "rgba(255,255,255,.82)"},
    })
    pio.templates.default = "lunkuo"
    st.markdown("""
    <style>
    :root{--navy:#081a2f;--navy2:#0d2b4b;--blue:#176eae;--cyan:#20b7d3;--ink:#132238;--muted:#66778c;--line:#dbe6ef;--bg:#f3f7fb;--white:#fff;--r:14px;--shadow:0 8px 26px rgba(16,48,82,.08)}
    html,body,[class*="css"]{font-family:Inter,"Microsoft YaHei","PingFang SC",sans-serif}.stApp{background:var(--bg);color:var(--ink)}
    header[data-testid="stHeader"]{background:rgba(243,247,251,.84);backdrop-filter:blur(14px)}#MainMenu,footer{visibility:hidden}
    section[data-testid="stSidebar"]{width:280px!important;min-width:280px!important;max-width:280px!important;background:linear-gradient(180deg,#061425,var(--navy) 55%,var(--navy2))!important;border-right:1px solid rgba(255,255,255,.08);box-shadow:8px 0 30px rgba(7,20,38,.13)}
    section[data-testid="stSidebar"]>div{width:280px!important}section[data-testid="stSidebar"] *{color:#dceafa}
    section[data-testid="stSidebar"] [data-testid="stSidebarNav"]{padding-top:1rem}
    section[data-testid="stSidebar"] [data-testid="stSidebarNav"]:before{content:"LUNKUO  ·  DATA OS";display:block;margin:6px 18px 18px;padding:16px 14px;border:1px solid rgba(255,255,255,.1);border-radius:16px;background:linear-gradient(135deg,rgba(32,183,211,.2),rgba(23,110,174,.18));color:#fff;font-size:13px;font-weight:800;letter-spacing:1.2px}
    section[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"]{margin:3px 10px;padding:10px 12px;border-radius:11px;border:1px solid transparent;transition:.18s ease}
    section[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"]:hover{background:rgba(255,255,255,.08);border-color:rgba(255,255,255,.08);transform:translateX(2px)}
    section[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"][aria-current="page"]{background:linear-gradient(90deg,rgba(32,183,211,.27),rgba(23,110,174,.18));border-color:rgba(80,210,232,.25);box-shadow:inset 3px 0 0 #4bd1e8}
    section[data-testid="stSidebar"] hr{border-color:rgba(255,255,255,.12)!important}
    .main .block-container{width:100%;max-width:1680px;padding:2rem 2.2rem 4rem}h1,h2,h3,h4{color:var(--ink)!important;letter-spacing:-.025em}h1{font-size:2rem!important;font-weight:790!important}h2{font-size:1.55rem!important;font-weight:760!important}h3{font-size:1.2rem!important;font-weight:720!important}p,label,.stCaption{color:var(--muted)}hr{border:0!important;border-top:1px solid var(--line)!important;margin:1.2rem 0!important}
    div[data-testid="stMetric"]{min-height:116px;padding:18px 19px;border:1px solid var(--line);border-radius:var(--r);background:linear-gradient(145deg,#fff,#f9fcff);box-shadow:0 2px 8px rgba(16,48,82,.06);position:relative;overflow:hidden;transition:.18s ease}
    div[data-testid="stMetric"]:before{content:"";position:absolute;left:0;top:0;right:0;height:3px;background:linear-gradient(90deg,var(--blue),var(--cyan))}div[data-testid="stMetric"]:hover{transform:translateY(-2px);box-shadow:var(--shadow)}
    div[data-testid="stMetricLabel"]{font-size:.82rem;font-weight:660;color:var(--muted)}div[data-testid="stMetricValue"]{font-size:1.72rem;font-weight:800;color:var(--ink);letter-spacing:-.04em}
    div[data-testid="stVerticalBlockBorderWrapper"],div[data-testid="stExpander"]{border:1px solid var(--line)!important;border-radius:18px!important;background:#fff;box-shadow:0 2px 8px rgba(16,48,82,.05);overflow:hidden}div[data-testid="stExpander"] summary{padding:.85rem 1rem;font-weight:680}
    div[data-testid="stTabs"] [data-baseweb="tab-list"]{gap:5px;padding:5px;border:1px solid var(--line);border-radius:14px;background:#eaf1f7;width:max-content;max-width:100%;overflow-x:auto}
    div[data-testid="stTabs"] button[role="tab"]{height:39px;padding:0 15px;border-radius:10px;font-size:.88rem;font-weight:670;color:var(--muted);border:0!important}div[data-testid="stTabs"] button[role="tab"][aria-selected="true"]{color:#123c63;background:#fff;box-shadow:0 2px 8px rgba(16,48,82,.1)}div[data-testid="stTabs"] [data-baseweb="tab-highlight"]{display:none}
    .stButton>button,.stDownloadButton>button{min-height:40px;border-radius:10px!important;border:1px solid #cbd9e6!important;background:#fff!important;color:#154872!important;font-weight:680!important;box-shadow:0 1px 3px rgba(16,48,82,.05);transition:.16s ease!important}.stButton>button:hover,.stDownloadButton>button:hover{border-color:var(--blue)!important;color:var(--blue)!important;box-shadow:0 5px 15px rgba(23,110,174,.13);transform:translateY(-1px)}
    /* Streamlit 会给按钮内部的 p/span 单独设置灰色；强制内部文字继承按钮前景色。 */
    .stButton>button *,.stDownloadButton>button *,button[data-testid^="stBaseButton"] *{color:inherit!important;-webkit-text-fill-color:currentColor!important}
    button[data-testid="stBaseButton-primary"],.stButton>button[kind="primary"],.stDownloadButton>button[kind="primary"]{color:#fff!important;border-color:transparent!important;background:linear-gradient(135deg,#1767a5,#1687c9)!important;box-shadow:0 6px 16px rgba(23,110,174,.24)!important}
    button[data-testid="stBaseButton-primary"] *,button[kind="primary"] *{color:#fff!important;-webkit-text-fill-color:#fff!important}
    button[data-testid="stBaseButton-primary"]:hover,.stButton>button[kind="primary"]:hover,.stDownloadButton>button[kind="primary"]:hover{color:#fff!important;background:linear-gradient(135deg,#12598f,#1176b2)!important;border-color:transparent!important}
    .stButton>button:disabled,.stDownloadButton>button:disabled{opacity:.62!important;color:#51677d!important;background:#e8eef4!important;border-color:#ccd8e3!important}
    div[data-baseweb="input"]>div,div[data-baseweb="select"]>div,div[data-baseweb="textarea"]>div{border-color:#cad9e6!important;border-radius:10px!important;background:#fff!important}div[data-baseweb="input"]>div:focus-within,div[data-baseweb="select"]>div:focus-within,div[data-baseweb="textarea"]>div:focus-within{border-color:#1687c9!important;box-shadow:0 0 0 3px rgba(22,135,201,.12)!important}
    div[data-testid="stFileUploader"] section{border:1.5px dashed #aac2d7;border-radius:14px;background:#f8fbfe}div[data-testid="stFileUploader"] section:hover{border-color:#1687c9;background:#edf7ff}
    div[data-testid="stDataFrame"],div[data-testid="stTable"],div[data-testid="stPlotlyChart"]{border:1px solid var(--line);border-radius:var(--r);overflow:hidden;background:#fff;box-shadow:0 2px 8px rgba(16,48,82,.05)}div[data-testid="stAlert"]{border-radius:12px;border-width:1px;box-shadow:0 2px 8px rgba(16,48,82,.05)}
    .page-hero{display:flex;justify-content:space-between;align-items:flex-end;gap:20px;margin:0 0 22px;padding:22px 24px;border:1px solid var(--line);border-radius:20px;background:linear-gradient(135deg,#fff 0%,#eef8ff 70%,#e9fbfd 100%);box-shadow:0 3px 12px rgba(16,48,82,.06)}.page-hero__eyebrow{color:#176eae;font-size:12px;font-weight:800;letter-spacing:1.4px}.page-hero__title{color:var(--ink);font-size:29px;line-height:1.18;font-weight:800;margin:5px 0 6px;letter-spacing:-.035em}.page-hero__subtitle{color:var(--muted);font-size:14px;margin:0}.page-hero__badge{white-space:nowrap;padding:8px 12px;border-radius:999px;background:#fff;border:1px solid #cfe1ef;color:#17609a;font-size:12px;font-weight:750}
    @media(max-width:900px){section[data-testid="stSidebar"]{width:245px!important;min-width:245px!important;max-width:245px!important}section[data-testid="stSidebar"]>div{width:245px!important}.main .block-container{padding:1.4rem 1rem 3rem}.page-hero{align-items:flex-start;flex-direction:column;padding:18px}.page-hero__title{font-size:24px}}
    @media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
    </style>""", unsafe_allow_html=True)


def page_header(title, subtitle, eyebrow="DATA WORKSPACE", badge=None):
    badge_html = f'<div class="page-hero__badge">{badge}</div>' if badge else ""
    st.markdown(f'''<div class="page-hero"><div><div class="page-hero__eyebrow">{eyebrow}</div><div class="page-hero__title">{title}</div><p class="page-hero__subtitle">{subtitle}</p></div>{badge_html}</div>''', unsafe_allow_html=True)
