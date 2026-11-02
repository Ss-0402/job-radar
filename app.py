# 岗位雷达 v4.8 · 部署版
# 数据与代码分离：岗位数据在 jd.json，改数据不用碰代码。
#
# v4.8：刷新时先显示过渡页，不再闪一下登录表单。
# v4.7：登录页与侧栏零散小字合并成「用户须知 / 关于」折叠区，视觉更干净。
# v4.6：主区改成分页 + JD 弹窗，单次渲染元素从 ~600 降到 ~70，交互明显变快。
# v4.5：登录凭证存进浏览器 sessionStorage（刷新保留 / 关标签页即退出，不进地址栏）。
# v4.2：简历支持 txt / docx / pdf 上传（扫描件会给出明确提示）。
# v4.1：整页登录——未登录只有登录/注册界面，登录后才能进入岗位列表。
# v4.0：本地账号（用户名+密码，PBKDF2 哈希），每账号每天 3 次 AI 解析。
# v3.7：同一份简历只解析一次、全站每日总额度、输入截断与超时。
#
# 运行（本地）：streamlit run app.py
# 部署：推送到 GitHub，Streamlit Cloud 自动重建

import json
import os
import re
import secrets as pysecrets
from pathlib import Path

import streamlit as st
from openai import OpenAI

import docs
import quota
import tokens
import users

# 页面级配置必须是第一条 Streamlit 命令
st.set_page_config(page_title="岗位雷达", page_icon="🎯")

HERE = Path(__file__).resolve().parent
DATA_FILE = HERE / "jd.json"

# ============================================================
# 参数
# ============================================================
MAX_CHARS_IN = 6000      # 送模型的简历最多截这么长，控制单次 token
MAX_TOKENS_OUT = 400     # 模型输出上限（JSON 很短，400 足够）
REQ_TIMEOUT = 20         # 单次请求超时，免得用户干等
FREE_PER_DAY = 3         # 每个登录账号每天免费解析次数
DAILY_CAP = 100          # 全站每天总次数，兜底防刷
PAGE_SIZE = 10           # 列表一次渲染多少张卡（多了浏览器会明显卡）
# 额度文件路径可用环境变量覆盖（测试、或挂载持久卷时用）
QUOTA_FILE = Path(os.getenv("JOB_RADAR_QUOTA_FILE") or (HERE / ".ai_quota.json"))
USERS_FILE = Path(os.getenv("JOB_RADAR_USERS_FILE") or (HERE / ".users.json"))

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
# 账号（本地用户名 + 密码，不做邮箱验证）
# 未登录只能看到登录页；登录后才能进入岗位列表。
# 登录状态写进浏览器 cookie（HMAC 签名，7 天），刷新页面不用重新登录。
# ============================================================

TOKEN_HOURS = 12                 # 凭证兜底有效期
BUILD_TAG = "v4.8"               # 版本标记：用来确认线上跑的是哪一版
STORAGE_ENABLED = os.getenv("JOB_RADAR_STORAGE", "on") != "off"

if "user" not in st.session_state:
    st.session_state.user = None        # 登录后存用户名（小写键）

_SECRET_CACHE: str | None = None
_STORAGE = None


def _auth_secret() -> str:
    """签名密钥：优先 Secrets，其次环境变量，最后进程内随机（重启后旧 token 失效）。"""
    global _SECRET_CACHE
    if _SECRET_CACHE:
        return _SECRET_CACHE
    for getter in (
        lambda: st.secrets["AUTH_SECRET"],
        lambda: os.getenv("JOB_RADAR_AUTH_SECRET"),
    ):
        try:
            value = str(getter() or "")
            if value:
                _SECRET_CACHE = value
                return value
        except Exception:
            continue
    _SECRET_CACHE = pysecrets.token_hex(32)
    return _SECRET_CACHE


def _storage(**kwargs):
    """浏览器 sessionStorage 桥（见 auth_store/index.html）。

    用它而不是 cookie：会话 cookie 关闭标签页不会被清，
    而产品要求“关标签页 / 关浏览器都要退出登录”。
    """
    global _STORAGE
    if _STORAGE is None:
        import streamlit.components.v1 as components

        _STORAGE = components.declare_component(
            "auth_store", path=str(HERE / "auth_store")
        )
    return _STORAGE(default=None, **kwargs)


def _resolve_token(token) -> str:
    """cookie/storage 里的凭证 → 用户名；无效返回空串。"""
    if not token:
        return ""
    name = tokens.verify(token, _auth_secret())
    if name and users.exists(USERS_FILE, name):
        return name
    return ""


def _restore_login() -> str:
    """尝试从 sessionStorage 恢复登录。

    返回：
      "app"     —— 已登录，正常渲染主界面
      "login"   —— 没登录，渲染登录页
      "probing" —— 组件还没回值，渲染过渡页（避免先闪一下登录页）
    """
    if st.session_state.pop("just_logged_out", False):
        if STORAGE_ENABLED:
            _storage(mode="clear", key="auth_clear")
        st.session_state.auth_probed = True
        return "login"

    if st.session_state.user:
        return "app"
    if st.session_state.get("auth_probed") or not STORAGE_ENABLED:
        return "login"

    stored = _storage(mode="get", key="auth_get")
    if stored is None:                  # 组件还没回值：给过渡页，别画登录表单
        return "probing"

    st.session_state.auth_probed = True
    name = _resolve_token(stored)
    if name:
        st.session_state.user = name
        return "app"
    return "login"


def _probing_screen() -> None:
    """过渡页：只显示标题和一句提示，避免登录页一闪而过。

    带一个「直接登录」兜底按钮——万一浏览器端组件失效，用户不会卡死。
    """
    st.markdown(
        "<style>[data-testid='stSidebar']{display:none;}"
        "[data-testid='collapsedControl']{display:none;}</style>",
        unsafe_allow_html=True,
    )
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.write("")
        st.markdown("### 🎯 岗位雷达")
        st.write("")
        st.markdown("进入中…")
        if st.button("直接登录", use_container_width=True):
            st.session_state.auth_probed = True
            st.rerun()
    st.stop()


def _persist_login() -> None:
    """登录成功后把凭证写进 sessionStorage（下一次运行执行，避免被 rerun 拆掉）。"""
    pending = st.session_state.pop("pending_token", None)
    if pending and STORAGE_ENABLED:
        _storage(mode="set", token=pending, key="auth_set")


def _current_user() -> str:
    return st.session_state.user or ""


def _login_form() -> None:
    tab_login, tab_reg = st.tabs(["登录", "注册"])

    with tab_login:
        name = st.text_input("用户名", key="li_name")
        pwd = st.text_input("密码", type="password", key="li_pwd")
        remember = st.checkbox("保持登录（刷新不用重登）", value=True, key="li_remember")
        if st.button("登录", use_container_width=True, key="li_btn", type="primary"):
            ok, info = users.authenticate(USERS_FILE, name, pwd)
            if ok:
                st.session_state.user = name.strip().lower()
                if remember:
                    st.session_state.pending_token = tokens.make(
                        st.session_state.user, _auth_secret(), TOKEN_HOURS / 24
                    )
                st.rerun()
            else:
                st.error(info)

    with tab_reg:
        rname = st.text_input("用户名", key="rg_name",
                              help="3–20 位，字母、数字、下划线或中文")
        rpwd = st.text_input("密码", type="password", key="rg_pwd",
                             help=f"至少 {users.MIN_PASSWORD} 位，别用其他网站的密码")
        rpwd2 = st.text_input("确认密码", type="password", key="rg_pwd2")
        if st.button("注册并登录", use_container_width=True, key="rg_btn"):
            if rpwd != rpwd2:
                st.error("两次输入的密码不一致")
            else:
                ok, info = users.register(USERS_FILE, rname, rpwd)
                if ok:
                    st.session_state.user = rname.strip().lower()
                    st.session_state.pending_token = tokens.make(
                        st.session_state.user, _auth_secret(), TOKEN_HOURS / 24
                    )
                    st.rerun()
                else:
                    st.error(info)


def _login_page() -> None:
    """整页登录：隐藏侧栏，中间一张卡片。"""
    st.markdown(
        "<style>[data-testid='stSidebar']{display:none;}"
        "[data-testid='collapsedControl']{display:none;}</style>",
        unsafe_allow_html=True,
    )

    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.write("")
        st.markdown("### 🎯 岗位雷达")
        st.markdown("上传简历，按 60 条岗位的匹配度排序，看出你还缺什么。")

        with st.container(border=True):
            _login_form()

        with st.expander("📋 用户须知"):
            st.markdown(
                f"""
**免费额度**　每个账号每天 {FREE_PER_DAY} 次 AI 解析，规则匹配不限次。

**登录用途**　仅用于识别账号和计次，不收邮箱、不发验证邮件。

**密码**　演示账号，请勿使用你在其他网站的密码。

**登录状态**　只保存在当前标签页：刷新保留，关闭标签页或浏览器即退出。

**数据**　岗位为模拟数据，仅用于演示。

当前版本 `{BUILD_TAG}`
"""
            )

    st.stop()


_auth_state = _restore_login()
if _auth_state == "probing":
    _probing_screen()

_persist_login()

USER = _current_user()

if not USER:
    _login_page()


# ============================================================
# 四、会话状态
# ============================================================
if "favs" not in st.session_state:
    st.session_state.favs = set()
if "parsed" not in st.session_state:
    st.session_state.parsed = None      # AI 解析结果，避免重复花钱
if "parsed_text" not in st.session_state:
    st.session_state.parsed_text = ""   # 已经解析过的原文，同一份不再花钱
if "shown" not in st.session_state:
    st.session_state.shown = PAGE_SIZE  # 列表分页：一次只渲染这么多张卡

# ============================================================
# 五、侧边栏
# ============================================================
with st.sidebar:
    top_left, top_right = st.columns([3, 2])
    with top_left:
        st.caption(f"👤 {users.display_name(USERS_FILE, USER)}")
    with top_right:
        if st.button("退出", use_container_width=True, key="logout"):
            st.session_state.user = None
            st.session_state.just_logged_out = True
            st.rerun()

    with st.expander("📄 简历", expanded=True):
        tab_paste, tab_upload = st.tabs(["粘贴", "上传"])
        with tab_paste:
            pasted = st.text_area("简历正文", height=140, key="resume_paste",
                                  label_visibility="collapsed",
                                  placeholder="把技能、项目经历粘进来……")
        with tab_upload:
            uploaded = st.file_uploader("txt / docx / pdf", type=docs.SUPPORTED,
                                        label_visibility="collapsed")

        resume_text = pasted or ""
        if uploaded is not None:
            ok, text_or_msg = docs.to_text(uploaded.name, uploaded.getvalue())
            if ok:
                resume_text = text_or_msg
            else:
                st.error(text_or_msg)

        btn_parse, btn_clear = st.columns(2)
        with btn_parse:
            if st.button("AI 解析", use_container_width=True, type="primary",
                         help="调用大模型，约一分钱"):
                if not resume_text.strip():
                    st.warning("先粘贴简历")
                elif client is None:
                    st.warning("未配置 API Key，只能用规则匹配")
                elif st.session_state.parsed and st.session_state.parsed_text == resume_text:
                    st.info("这份简历已经解析过，直接复用结果（不再花钱）")
                elif not quota.try_take(QUOTA_FILE, USER, FREE_PER_DAY, DAILY_CAP):
                    st.warning(
                        f"今天的 {FREE_PER_DAY} 次免费额度已用完，明天 0 点恢复。"
                        "规则匹配不受影响。"
                    )
                else:
                    with st.spinner("解析中……"):
                        parsed = llm_extract(resume_text)
                    if parsed:
                        st.session_state.parsed = parsed
                        st.session_state.parsed_text = resume_text
                    else:
                        st.error("解析失败，已退回规则匹配")
        with btn_clear:
            if st.button("清空", use_container_width=True):
                st.session_state.parsed = None
                st.session_state.parsed_text = ""
                st.rerun()

        if client is None:
            st.caption("未配置 API Key：只用规则匹配。")
        else:
            left = quota.remaining(QUOTA_FILE, USER, FREE_PER_DAY)
            st.caption(f"今日 AI 解析剩余 {left}/{FREE_PER_DAY}")

    my_skills = (
        set(st.session_state.parsed.get("skills", []))
        if st.session_state.parsed
        else set(rule_extract(resume_text or "")["skills"])
    )
    if my_skills:
        source = "AI" if st.session_state.parsed else "规则"
        st.caption(f"{source}识别 {len(my_skills)} 项：{'、'.join(sorted(my_skills))}")

    with st.expander("🔍 筛选", expanded=False):
        dir_options = sorted({j["direction"] for j in JOBS})
        city_options = sorted({j["city"] for j in JOBS})
        sel_dirs = st.multiselect("岗位方向", dir_options)
        sel_cities = st.multiselect("城市", city_options)
        sel_degs = st.multiselect("学历要求", ["大专", "本科", "硕士"])

    with st.expander("ℹ️ 关于"):
        st.caption(f"岗位雷达 {BUILD_TAG} · 岗位为模拟数据，仅用于演示")

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
@st.dialog("JD 全文", width="large")
def _jd_dialog(job) -> None:
    st.markdown(f"**{job['title']}**")
    st.caption(f"{job['company']} · {job['city']} · {job['degree']} · {job['direction']}")
    st.markdown(highlight(job["jd"], job["skills"]))
    st.code(job["jd"], language=None)


st.title("🎯 岗位雷达")
st.caption(f"{len(JOBS)} 条岗位 · 点「查看 JD」看原文 · 有简历时按匹配度排序")

c1, c2, c3 = st.columns(3)
c1.metric("符合条件的岗位", len(filtered))
c2.metric("已收藏", len(st.session_state.favs))
if my_skills and filtered:
    avg = sum(match_score(j, my_skills)[0] for j in filtered) / len(filtered)
    c3.metric("平均匹配度", f"{avg*100:.0f}%")
else:
    c3.metric("平均匹配度", "—")
    st.caption("左侧「📄 简历」里粘贴或上传简历，就能按匹配度排序并看到缺口。")

if not filtered:
    st.warning("没有符合条件的岗位，试试放宽筛选。")
    st.stop()

if my_skills:
    filtered.sort(key=lambda j: match_score(j, my_skills)[0], reverse=True)

visible = filtered[: st.session_state.shown]

for job in visible:
    score, have, missing = match_score(job, my_skills) if my_skills else (0, set(), set())
    is_fav = job["id"] in st.session_state.favs

    with st.container(border=True):
        head, tail = st.columns([7, 1])
        with head:
            st.markdown(f"**{job['title']}**")
            st.caption(
                f"{job['company']} · {job['city']} · {job['degree']} · {job['direction']}"
                f" · {' '.join(job['skills'])}"
            )
        with tail:
            if st.button("★" if is_fav else "☆", key=f"fav_{job['id']}",
                         use_container_width=True, help="收藏 / 取消收藏"):
                st.session_state.favs.symmetric_difference_update({job["id"]})
                st.rerun()

        if my_skills:
            st.progress(min(score, 1.0), text=f"匹配 {score*100:.0f}% · 缺 {len(missing)} 项")
        if missing:
            st.caption("⚠️ " + "、".join(sorted(missing)))

        if st.button("查看 JD", key=f"jd_{job['id']}"):
            _jd_dialog(job)

remaining = len(filtered) - len(visible)
if remaining > 0:
    if st.button(f"再看 {min(PAGE_SIZE, remaining)} 条（还有 {remaining} 条）",
                 use_container_width=True):
        st.session_state.shown += PAGE_SIZE
        st.rerun()

st.divider()
st.caption("数据为模拟岗位，仅用于演示；真实项目请替换 jd.json。")
