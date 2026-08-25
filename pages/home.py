# -*- coding: utf-8 -*-
import html
import json

import streamlit as st
import streamlit.components.v1 as components

from core.app_config import load_carousel_config
from core.theme import page_header


st.set_page_config(page_title="主页", layout="wide")

page_header(
    f"欢迎回来，{st.session_state.get('username', '伙伴')}",
    "从这里进入经营分析工作区，快速查看关键指标与业务机会",
    "LUNKUO DATA OS",
    "数据已连接",
)

config = load_carousel_config()
slides = config.get("slides", [])
interval_ms = int(config.get("interval_seconds", 5)) * 1000

safe_slides = []
for slide in slides:
    safe_slides.append({
        "image_url": html.escape(str(slide.get("image_url", "")), quote=True),
        "title": html.escape(str(slide.get("title", ""))),
        "subtitle": html.escape(str(slide.get("subtitle", ""))),
        "link_url": html.escape(str(slide.get("link_url", "")), quote=True),
    })

slides_json = json.dumps(safe_slides, ensure_ascii=False)
components.html(
    f"""
    <div id="hero" class="hero"></div>
    <div id="dots" class="dots"></div>
    <style>
      * {{ box-sizing: border-box; }}
      html, body {{ margin: 0; padding: 0; overflow: hidden; font-family: Inter, 'Microsoft YaHei', sans-serif; }}
      body {{ position: relative; }}
      .hero {{
        width: min(100%, 960px); max-width: 960px; aspect-ratio: 4 / 3; height: auto;
        margin: 0;
        border-radius: 24px; overflow: hidden; position: relative;
        background: linear-gradient(135deg, #0f172a, #1d4ed8 55%, #38bdf8);
        box-shadow: 0 20px 55px rgba(15,23,42,.18);
      }}
      .slide {{ position:absolute; inset:0; opacity:0; transition:opacity .55s ease; }}
      .slide.active {{ opacity:1; }}
      .slide-bg {{ position:absolute; inset:0; background-size:cover; background-position:center; }}
      .slide-bg::after {{ content:''; position:absolute; inset:0; background:linear-gradient(90deg,rgba(2,6,23,.82),rgba(2,6,23,.25)); }}
      .copy {{ position:absolute; left:7%; top:50%; transform:translateY(-50%); color:white; max-width:620px; z-index:2; }}
      h1 {{ font-size:44px; margin:0 0 16px; line-height:1.15; }}
      p {{ font-size:18px; line-height:1.7; color:#dbeafe; margin:0; }}
      .cta {{ display:inline-block; margin-top:24px; padding:11px 20px; border-radius:999px; background:white; color:#0f172a; text-decoration:none; font-weight:700; }}
      .dots {{ position:absolute; z-index:3; left:0; right:0; bottom:18px; display:flex; justify-content:center; gap:8px; }}
      .dot {{ width:9px; height:9px; padding:0; border-radius:50%; background:rgba(255,255,255,.58); border:0; cursor:pointer; }}
      .dot.active {{ width:28px; border-radius:8px; background:white; }}
    </style>
    <script>
      const slides = {slides_json};
      const hero = document.getElementById('hero');
      const dots = document.getElementById('dots');
      let current = 0;
      slides.forEach((s, i) => {{
        const el = document.createElement('div'); el.className = 'slide' + (i===0?' active':'');
        const bg = s.image_url ? `background-image:url('${{s.image_url}}')` : '';
        const cta = s.link_url ? `<a class="cta" href="${{s.link_url}}" target="_self">了解更多</a>` : '';
        el.innerHTML = `<div class="slide-bg" style="${{bg}}"></div><div class="copy"><h1>${{s.title}}</h1><p>${{s.subtitle}}</p>${{cta}}</div>`;
        hero.appendChild(el);
        const dot = document.createElement('button'); dot.className='dot'+(i===0?' active':''); dot.onclick=()=>show(i); dots.appendChild(dot);
      }});
      function show(i) {{
        const items=[...hero.children], ds=[...dots.children];
        items.forEach((x,n)=>x.classList.toggle('active',n===i)); ds.forEach((x,n)=>x.classList.toggle('active',n===i)); current=i;
      }}
      if (slides.length > 1) setInterval(()=>show((current+1)%slides.length), {interval_ms});
      function syncFrameHeight() {{
        const height = Math.ceil(hero.getBoundingClientRect().height);
        window.parent.postMessage({{isStreamlitMessage: true, type: 'streamlit:setFrameHeight', height}}, '*');
      }}
      new ResizeObserver(syncFrameHeight).observe(hero);
      window.addEventListener('resize', syncFrameHeight);
      requestAnimationFrame(syncFrameHeight);
    </script>
    """,
    width=960,
    height=720,
)

st.markdown("### 快速开始")
st.markdown("""<style>
.quick-card{min-height:142px;padding:22px;border:1px solid #dbe6ef;border-radius:16px;background:linear-gradient(145deg,#fff,#f9fcff);box-shadow:0 3px 12px rgba(16,48,82,.06);transition:.18s ease}.quick-card:hover{transform:translateY(-3px);box-shadow:0 12px 28px rgba(16,48,82,.11);border-color:#b8d4e7}.quick-icon{width:44px;height:44px;display:flex;align-items:center;justify-content:center;border-radius:12px;background:linear-gradient(135deg,#e7f5ff,#e8fbfd);font-size:22px}.quick-title{font-size:16px;font-weight:760;color:#132238;margin:14px 0 6px}.quick-desc{font-size:13px;line-height:1.55;color:#66778c;margin:0}
</style>""", unsafe_allow_html=True)
cols = st.columns(4)
cards = [
    ("📊", "经营驾驶舱", "查看核心经营指标、趋势和异常提醒"),
    ("📦", "商品分析", "按本月数据分析商品表现与退货风险"),
    ("🎤", "主播分析", "洞察主播贡献、货品结构与增长空间"),
    ("🏢", "组织与部门", "查看组织、部门与店铺的经营贡献"),
]
for col, (icon, title, desc) in zip(cols, cards):
    with col:
        st.markdown(f"<div class='quick-card'><div class='quick-icon'>{icon}</div><div class='quick-title'>{title}</div><p class='quick-desc'>{desc}</p></div>", unsafe_allow_html=True)
