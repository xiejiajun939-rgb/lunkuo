# -*- coding: utf-8 -*-
import streamlit as st
from openai import OpenAI
import time

@st.cache_resource
def get_siliconflow_client():
    try:
        api_key = st.secrets["SILICONFLOW_API_KEY"]
        client = OpenAI(api_key=api_key, base_url="https://api.siliconflow.cn/v1")
        return client
    except Exception as e:
        st.error(f"硅基流动客户端初始化失败: {e}")
        return None

@st.cache_data(ttl=3600)
def get_ai_summary(prompt: str, context: str, model: str) -> str:
    client = get_siliconflow_client()
    if not client:
        return "⚠️ AI 服务暂不可用，请稍后再试。"
    messages = [{"role": "system", "content": prompt}, {"role": "user", "content": context}]
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(model=model, messages=messages, stream=False)
            return response.choices[0].message.content
        except Exception as e:
            if attempt == max_retries - 1:
                return f"❌ AI 总结失败，请稍后再试。错误: {str(e)}"
            time.sleep(1 * (2 ** attempt))
    return "⚠️ AI 服务暂时无法响应。"
