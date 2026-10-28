# 岗位雷达 v1 · 部署版
# 和 第11课/02_app.py 的区别只有两处：
#   1. API Key 从 st.secrets 读（云端没有 .env）
#   2. JD 数据和代码放在同一目录，路径用相对路径

import json
import os
from pathlib import Path

import streamlit as st
from openai import OpenAI

# ---------- 读取 API Key ----------
# 本地：环境变量 / .env（用 python-dotenv 时）
# 云端：Streamlit Cloud 的 Secrets（就是 st.secrets）
try:
    API_KEY = st.secrets["DEEPSEEK_API_KEY"]
except Exception:
    API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

BASE_URL = "https://api.deepseek.com"

client = OpenAI(api_key=API_KEY, base_url=BASE_URL) if API_KEY else None

HERE = Path(__file__).resolve().parent
JD_FILE = HERE / "jd.json"

SYSTEM = """你是一名资深技术招聘官。
【任务】抽取 name（姓名）、years（工作年限，整数）、skills（技能，字符串数组，最多 5 个）、direction（求职方向）
【格式】只输出一个 JSON 对象，不要解释，不要 markdown 代码块。
【约束】只依据原文，不编造；缺失的字段用 ""、0 或 [] 表示。"""


def extract(resume_text):
    r = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": resume_text},
        ],
        temperature=0,
    )
    raw = r.choices[0].message.content
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def score_one(resume, jd):
    my = {s.lower().strip() for s in resume.get("skills", [])}
    need = {s.lower().strip() for s in jd.get("skills", [])}
    hit = my & need
    missing = need - my
    skill_score = len(hit) / len(need) if need else 0
    need_years = jd.get("min_years", 0)
    year_score = 1.0 if need_years == 0 else min(resume.get("years", 0) / need_years, 1.0)
    return skill_score * 0.7 + year_score * 0.3, hit, missing


st.set_page_config(page_title="岗位雷达", page_icon="🎯")
st.title("🎯 岗位雷达")
st.caption("粘贴简历，看看哪些岗位最适合你")

if client is None:
    st.error("没有读到 API Key。云端请在 Settings → Secrets 里配置 DEEPSEEK_API_KEY。")
    st.stop()

resume_text = st.text_area("把简历文本粘贴到这里", height=220)

if st.button("开始分析", type="primary"):
    if not resume_text.strip():
        st.warning("先粘贴简历")
    else:
        with st.spinner("正在抽取简历信息……"):
            data = extract(resume_text)

        if data is None:
            st.error("抽取失败，模型没有返回合法 JSON。再试一次？")
        else:
            st.success("抽取完成")
            st.json(data)

            jds = json.loads(JD_FILE.read_text(encoding="utf-8"))
            scored = []
            for jd in jds:
                total, hit, missing = score_one(data, jd)
                scored.append((total, jd, hit, missing))
            scored.sort(key=lambda x: x[0], reverse=True)

            st.subheader("匹配结果")
            rows = []
            for total, jd, hit, missing in scored[:3]:
                rows.append(
                    {
                        "分数": round(total * 100, 1),
                        "岗位": jd["title"],
                        "公司": jd["company"],
                        "命中": "、".join(sorted(hit)) or "无",
                        "缺口": "、".join(sorted(missing)) or "无",
                    }
                )
            st.dataframe(rows, use_container_width=True)
