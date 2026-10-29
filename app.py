# 岗位雷达 v2 · 部署版
# v2 相比 v1 的改动：
#   1. JD 库扩到 20 条（真实岗位画像，不再是 6 条示例）
#   2. 支持上传 .txt 简历文件（不用再手工复制粘贴）
#   3. 结果改成卡片 + 指标，不再是裸表格
#   4. 首次加载提示（免费版冷启动 10–30 秒）

import json
import os
from pathlib import Path

import streamlit as st
from openai import OpenAI

try:
    API_KEY = st.secrets["DEEPSEEK_API_KEY"]
except Exception:
    API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com") if API_KEY else None

HERE = Path(__file__).resolve().parent
JD_FILE = HERE / "jd.json"

SYSTEM = """你是一名资深技术招聘官。
【任务】抽取 name（姓名）、years（工作年限，整数）、skills（技能，字符串数组，最多 5 个）、direction（求职方向）
【格式】只输出一个 JSON 对象，不要解释，不要 markdown 代码块。
【约束】只依据原文，不编造；缺失的字段用 ""、0 或 [] 表示。"""


def extract(text):
    r = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": text},
        ],
        temperature=0,
    )
    try:
        return json.loads(r.choices[0].message.content)
    except json.JSONDecodeError:
        return None


def score_one(resume, jd):
    my = {s.lower().strip() for s in resume.get("skills", [])}
    need = {s.lower().strip() for s in jd.get("skills", [])}
    hit = my & need
    missing = need - my
    skill = len(hit) / len(need) if need else 0
    ny = jd.get("min_years", 0)
    years = 1.0 if ny == 0 else min(resume.get("years", 0) / ny, 1.0)
    return skill * 0.7 + years * 0.3, hit, missing


st.set_page_config(page_title="岗位雷达", page_icon="🎯", layout="wide")

st.markdown("## 🎯 岗位雷达")
st.caption("用大模型解析你的简历，从岗位库里挑出最匹配的几条，并告诉你缺什么。")

if client is None:
    st.error("没有读到 API Key。请在 Streamlit 后台 Settings → Secrets 配置 DEEPSEEK_API_KEY。")
    st.stop()

jds = json.loads(JD_FILE.read_text(encoding="utf-8"))

left, right = st.columns([1, 1])

with left:
    uploaded = st.file_uploader("上传简历（.txt）", type=["txt"])
    text_input = st.text_area("或者直接粘贴", height=200)

with right:
    st.markdown("#### 岗位库概览")
    c1, c2 = st.columns(2)
    c1.metric("岗位数量", len(jds))
    c2.metric("覆盖方向", len({jd["title"].split("（")[0] for jd in jds}))
    st.caption("首次打开较慢是免费版冷启动，通常 10–30 秒。")

resume_text = ""
if uploaded is not None:
    resume_text = uploaded.read().decode("utf-8", errors="ignore")
elif text_input.strip():
    resume_text = text_input

if st.button("开始分析", type="primary", use_container_width=True):
    if not resume_text.strip():
        st.warning("先上传文件或粘贴简历内容")
    else:
        with st.spinner("正在解析简历……"):
            data = extract(resume_text)

        if data is None:
            st.error("解析失败，模型没有返回合法 JSON，请再试一次。")
        elif not data.get("name") and not data.get("skills"):
            st.warning(
                "没有从这段文字里识别到简历信息。\n\n"
                "请粘贴简历正文（包含姓名、经历、技能等），而不是无关内容。"
            )
            st.stop()
        else:
            st.success(f"解析完成：{data.get('name') or '（未识别姓名）'}")

            m1, m2, m3 = st.columns(3)
            m1.metric("识别技能", len(data.get("skills", [])))
            m2.metric("工作年限", data.get("years", 0))
            m3.metric("求职方向", data.get("direction") or "未识别")

            with st.expander("查看解析出的原始 JSON"):
                st.json(data)

            scored = []
            for jd in jds:
                total, hit, missing = score_one(data, jd)
                scored.append((total, jd, hit, missing))
            scored.sort(key=lambda x: x[0], reverse=True)

            st.markdown("### 匹配结果 Top 5")
            for total, jd, hit, missing in scored[:5]:
                with st.container(border=True):
                    c1, c2, c3 = st.columns([1, 3, 3])
                    c1.metric("匹配度", f"{total*100:.0f}%")
                    c2.markdown(f"**{jd['title']}**  \n{jd['company']}")
                    c3.markdown(
                        f"**命中**：{'、'.join(sorted(hit)) or '无'}  \n"
                        f"**缺口**：{'、'.join(sorted(missing)) or '无'}"
                    )

            st.caption("匹配度 = 技能命中率 × 70% + 年限满足度 × 30%")
