# 岗位雷达 v3.7 · 部署版
# 数据与代码分离：岗位数据在 jd.json，改数据不用碰代码。
#
# v3.7：公开上线后的花钱防护——同一份简历只解析一次、单会话限次、每日总额度。
#
# 运行（本地）：streamlit run app.py
# 部署：推送到 GitHub，Streamlit Cloud 自动重建

import json
import os
import re
from datetime import datetime
from pathlib import Path

import streamlit as st
from openai import OpenAI

HERE = Path(__file__).resolve().parent
DATA_FILE = HERE / "jd.json"

# ============================================================
# 花钱防护参数（app 公开后，任何访问者都能点「AI 解析」）
# ============================================================
MAX_CHARS_IN = 6000      # 送模型的简历最多截这么长，控制单次 token
MAX_TOKENS_OUT = 400     # 模型输出上限（JSON 很短，400 足够）
REQ_TIMEOUT = 20         # 单次请求超时，免得用户干等
PER_SESSION_CAP = 5      # 一个浏览器会话最多成功调几次
DAILY_CAP = 100          # 整个 app 每天最多调几次（防换会话刷）
QUOTA_FILE = HERE / ".ai_quota.json"

# ============================================================
# 一、API Key（云端来自 Secrets，本地来自环境变量）
# ============================================================
try:
    API_KEY = st.secrets["DEEPSEEK_API_KEY"]
except Exception:
    API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com") if API_KEY else None

# ============================================================
# 二、读岗位数据
# ============================================================
if not DATA_FILE.exists():
    st.error(f"缺少数据文件：{DATA_FILE.name}")
    st.stop()

JOBS = json.loads(DATA_FILE.read_text(encoding="utf-8"))
ALL_SKILLS = sorted({s for j in JOBS for s in j.get("skills", [])})

# ============================================================
# 三、工具函数
# ============================================================

def rule_extract(text: str) -> dict:
    """不调模型的兜底：用技能词表做匹配。"""
    low = text.lower()
    skills = sorted({s for s in ALL_SKILLS if s.lower() in low})
    return {"name": "", "years": 0, "skills": skills, "direction": ""}


def llm_extract(text: str):
    """调模型抽取；失败返回 None。"""
    if client is None:
        return None
    try:
        r = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": (
                    "你是简历解析器。只输出 JSON，不要解释、不要代码块。"
                    '字段：name（字符串）、years（整数）、skills（字符串数组）、direction（字符串）。'
                    "缺失字段用空字符串、0 或 [] 表示，不要编造。"
                )},
                {"role": "user", "content": text[:MAX_CHARS_IN]},
            ],
            temperature=0,
            max_tokens=MAX_TOKENS_OUT,
            timeout=REQ_TIMEOUT,
        )
        data = json.loads(r.choices[0].message.content)
        # 模型偶尔给中文键，做一次兜底映射
        for cn, en in [("姓名", "name"), ("年限", "years"), ("技能", "skills"), ("方向", "direction")]:
            if cn in data and en not in data:
                data[en] = data[cn]
        return data
    except Exception:
        return None


# ============================================================
# 额度记账：每天一个新计数，写在 .ai_quota.json（已在 .gitignore）
# 写文件失败就放行——宁可多花几毛钱，也别让页面报错。
# ============================================================

def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def quota_used_today() -> int:
    try:
        data = json.loads(QUOTA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if data.get("date") != _today():
        return 0
    try:
        return int(data.get("count", 0))
    except Exception:
        return 0


def quota_left() -> int:
    return max(DAILY_CAP - quota_used_today(), 0)


def quota_take() -> bool:
    """占一次额度。并发下可能少记几次，够用就行。"""
    used = quota_used_today()
    if used >= DAILY_CAP:
        return False
    try:
        QUOTA_FILE.write_text(
            json.dumps({"date": _today(), "count": used + 1}), encoding="utf-8"
        )
    except Exception:
        pass
    return True


def highlight(text: str, skills) -> str:
    """JD 里出现的技能词标成橙色加粗。"""
    out = text
    for s in sorted(skills, key=len, reverse=True):
        out = re.sub(re.escape(s), lambda m: f":orange[**{m.group(0)}**]", out, flags=re.IGNORECASE)
    return out


def match_score(job, mine):
    """返回 (匹配度 0~1, 已掌握, 缺失)；比较前统一小写。"""
    need_map = {s.lower(): s for s in job.get("skills", [])}
    mine_low = {s.lower() for s in mine}
    have = {need_map[k] for k in need_map.keys() & mine_low}
    missing = {need_map[k] for k in need_map.keys() - mine_low}
    if not need_map:
        return 0.0, set(), set()
    return len(have) / len(need_map), have, missing


# ============================================================
# 四、会话状态
# ============================================================
if "favs" not in st.session_state:
    st.session_state.favs = set()
if "parsed" not in st.session_state:
    st.session_state.parsed = None      # AI 解析结果，避免重复花钱
if "parsed_text" not in st.session_state:
    st.session_state.parsed_text = ""   # 已经解析过的原文，同一份不再花钱
if "ai_calls" not in st.session_state:
    st.session_state.ai_calls = 0       # 本会话已调用次数

# ============================================================
# 五、侧边栏
# ============================================================
with st.sidebar:
    st.header("📄 我的简历")

    uploaded = st.file_uploader("上传 .txt", type=["txt"])
    resume_text = st.text_area("或直接粘贴", height=160,
                               placeholder="把技能、项目经历粘进来……")
    if uploaded is not None:
        resume_text = uploaded.read().decode("utf-8", errors="ignore")

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("AI 解析", use_container_width=True, help="调用大模型，约一分钱"):
            if not resume_text.strip():
                st.warning("先粘贴简历")
            elif client is None:
                st.warning("未配置 API Key，只能用规则匹配")
            elif st.session_state.parsed and st.session_state.parsed_text == resume_text:
                st.info("这份简历已经解析过，直接复用上次结果（不再花钱）")
            elif st.session_state.ai_calls >= PER_SESSION_CAP:
                st.warning(f"本会话已达 {PER_SESSION_CAP} 次上限，已改用规则匹配")
            elif not quota_take():
                st.warning("今日 AI 解析额度已用完，已改用规则匹配")
            else:
                st.session_state.ai_calls += 1
                with st.spinner("解析中……"):
                    parsed = llm_extract(resume_text)
                if parsed:
                    st.session_state.parsed = parsed
                    st.session_state.parsed_text = resume_text
                else:
                    st.error("解析失败，已退回规则匹配")
    with col_b:
        if st.button("清空", use_container_width=True):
            st.session_state.parsed = None
            st.session_state.parsed_text = ""
            st.rerun()

    if client is None:
        st.caption("未配置 API Key：只用规则匹配，不发请求。")
    else:
        left_session = max(PER_SESSION_CAP - st.session_state.ai_calls, 0)
        st.caption(
            f"AI 解析每份简历 1 次 · 本会话剩 {left_session} 次 · 今日剩 {quota_left()} 次"
        )

    if st.session_state.parsed:
        my_skills = set(st.session_state.parsed.get("skills", []))
        st.success(f"AI 识别到 {len(my_skills)} 项技能")
        if st.session_state.parsed.get("years"):
            st.caption(f"年限：{st.session_state.parsed['years']}")
    else:
        my_skills = set(rule_extract(resume_text or "")["skills"])
        if my_skills:
            st.info(f"规则识别到 {len(my_skills)} 项技能（点「AI 解析」更准）")

    if my_skills:
        st.write("、".join(sorted(my_skills)))

    st.divider()
    st.header("🔍 筛选")
    dir_options = sorted({j["direction"] for j in JOBS})
    city_options = sorted({j["city"] for j in JOBS})

    sel_dirs = st.multiselect("岗位方向", dir_options)
    sel_cities = st.multiselect("城市", city_options)
    sel_degs = st.multiselect("学历要求", ["大专", "本科", "硕士"])

# ============================================================
# 六、筛选
# ============================================================
def keep(j):
    if sel_dirs and j["direction"] not in sel_dirs:
        return False
    if sel_cities and j["city"] not in sel_cities:
        return False
    if sel_degs and j["degree"] not in sel_degs:
        return False
    return True


filtered = [j for j in JOBS if keep(j)]

# ============================================================
# 七、主区
# ============================================================
st.title("🎯 岗位雷达")
st.caption(f"共 {len(JOBS)} 条岗位 · 筛选 · 查看 JD · 对照简历找差距")

c1, c2, c3 = st.columns(3)
c1.metric("符合条件的岗位", len(filtered))
c2.metric("已收藏", len(st.session_state.favs))
if my_skills and filtered:
    avg = sum(match_score(j, my_skills)[0] for j in filtered) / len(filtered)
    c3.metric("平均匹配度", f"{avg*100:.0f}%")
else:
    c3.metric("平均匹配度", "—")

st.divider()

if not filtered:
    st.warning("没有符合条件的岗位，试试放宽筛选。")
    st.stop()

if my_skills:
    filtered.sort(key=lambda j: match_score(j, my_skills)[0], reverse=True)

for job in filtered:
    score, have, missing = match_score(job, my_skills) if my_skills else (0, set(), set())
    is_fav = job["id"] in st.session_state.favs

    with st.container(border=True):
        left, right = st.columns([5, 2])
        with left:
            st.markdown(f"#### {job['title']}")
            st.caption(f"{job['company']} · {job['city']} · {job['degree']} · {job['direction']}")
            st.markdown(" ".join(f"`{s}`" for s in job["skills"]))

            if my_skills:
                st.progress(min(score, 1.0), text=f"匹配度 {score*100:.0f}%")
                if have:
                    st.markdown("✅ **已掌握**：" + "、".join(sorted(have)))
                if missing:
                    st.markdown("⚠️ **还缺**：" + "、".join(sorted(missing)))
        with right:
            if st.button("★ 已收藏" if is_fav else "☆ 收藏", key=f"fav_{job['id']}",
                         use_container_width=True):
                st.session_state.favs.symmetric_difference_update({job["id"]})
                st.rerun()

        with st.expander("查看 JD 全文（关键词已高亮）"):
            st.markdown(highlight(job["jd"], job["skills"]))
            st.caption("右上角图标可一键复制：")
            st.code(job["jd"], language=None)

st.divider()
st.caption("数据为模拟岗位，仅用于演示；真实项目请替换 jd.json。")
