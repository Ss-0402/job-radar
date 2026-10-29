# 岗位雷达 v3.5 · 部署版
# 相比 v2 的改动：
#   1. 界面换成 v3 的工具风（筛选、卡片、进度条、收藏、高亮、一键复制）
#   2. 简历解析变成"可选"：点按钮才调 AI（省钱），失败自动退回规则匹配
#   3. 岗位数据内置 20 条，带城市/学历/方向，支持多条件筛选
#
# 运行（本地）：streamlit run app.py
# 部署：推送到 GitHub，Streamlit Cloud 自动重建

import json
import os
import re

import streamlit as st
from openai import OpenAI

# ============================================================
# 一、API Key（云端来自 Secrets，本地来自环境变量）
# ============================================================
try:
    API_KEY = st.secrets["DEEPSEEK_API_KEY"]
except Exception:
    API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com") if API_KEY else None

# ============================================================
# 二、数据（真实项目里换成 JD 库文件或接口）
# ============================================================
JOBS = [
    {"id": 1, "title": "AI 应用开发实习生", "company": "某 AI 创业公司", "city": "北京", "degree": "本科", "direction": "AI 应用",
     "skills": ["Python", "LangChain", "Prompt", "RAG"],
     "jd": "岗位职责：\n1. 参与大模型应用的需求分析与方案设计；\n2. 基于 LangChain 搭建 RAG 问答链路，完成文档切分、向量检索与效果调优；\n3. 编写 Prompt 模板，提升抽取与生成的稳定性。\n任职要求：\n1. 熟悉 Python，了解 DeepSeek 等大模型 API；\n2. 了解 RAG 基本原理；\n3. 本科及以上。"},
    {"id": 2, "title": "大模型应用工程师", "company": "某智能客服公司", "city": "上海", "degree": "本科", "direction": "AI 应用",
     "skills": ["Python", "RAG", "Prompt", "FastAPI", "Docker"],
     "jd": "岗位职责：\n1. 负责智能客服对话链路开发与优化；\n2. 建设知识库检索（RAG）能力；\n3. 使用 FastAPI 封装模型服务，配合 Docker 部署。\n任职要求：\n1. 2 年以上 Python 经验；\n2. 熟悉向量检索与 Prompt 工程；\n3. 有线上部署经验优先。"},
    {"id": 3, "title": "AI Agent 开发工程师", "company": "某效率工具团队", "city": "深圳", "degree": "本科", "direction": "AI 应用",
     "skills": ["Python", "Prompt", "Function Calling", "Agent"],
     "jd": "岗位职责：\n1. 设计并实现多步任务型 Agent；\n2. 负责工具调用协议设计与异常处理；\n3. 打磨任务完成率。\n任职要求：\n1. 熟悉 Python 与 LLM 调用机制；\n2. 有 Agent 编排经验优先；\n3. 良好的问题拆解能力。"},
    {"id": 4, "title": "LLM 算法工程师", "company": "某大模型公司", "city": "北京", "degree": "硕士", "direction": "算法",
     "skills": ["Python", "PyTorch", "Transformer", "微调", "CUDA"],
     "jd": "岗位职责：\n1. 负责继续预训练与指令微调；\n2. 搭建评测集分析模型短板；\n3. 优化训练效率。\n任职要求：\n1. 硕士及以上，熟悉 Transformer；\n2. 熟练 PyTorch，有分布式训练经验；\n3. 有论文或开源项目优先。"},
    {"id": 5, "title": "NLP 算法工程师", "company": "某 AI 公司", "city": "杭州", "degree": "硕士", "direction": "算法",
     "skills": ["Python", "NLP", "PyTorch", "Transformer"],
     "jd": "岗位职责：\n1. 负责文本分类、信息抽取；\n2. 跟进大模型业务落地；\n3. 参与数据标注与评测。\n任职要求：\n1. 熟悉常见 NLP 任务；\n2. 熟练 PyTorch；\n3. 有信息抽取经验优先。"},
    {"id": 6, "title": "机器学习实习生", "company": "某研究院", "city": "北京", "degree": "本科", "direction": "算法",
     "skills": ["Python", "PyTorch", "机器学习", "数据分析"],
     "jd": "岗位职责：\n1. 数据清洗与特征工程；\n2. 复现论文模型；\n3. 撰写实验记录。\n任职要求：\n1. 熟悉 Python 与机器学习算法；\n2. 了解 PyTorch；\n3. 每周到岗 4 天以上。"},
    {"id": 7, "title": "数据分析师", "company": "某零售集团", "city": "上海", "degree": "本科", "direction": "数据",
     "skills": ["Python", "SQL", "Excel", "数据分析", "可视化"],
     "jd": "岗位职责：\n1. 业务指标监控与异动分析；\n2. 搭建看板，输出周报；\n3. 配合 A/B 实验设计。\n任职要求：\n1. 熟练 SQL 与 Excel；\n2. 会 Python（Pandas）；\n3. 较强的业务理解能力。"},
    {"id": 8, "title": "数据开发工程师", "company": "某金融科技", "city": "深圳", "degree": "本科", "direction": "数据",
     "skills": ["SQL", "Python", "Spark", "数据仓库", "Linux"],
     "jd": "岗位职责：\n1. 数仓分层建模与 ETL 开发；\n2. 保障数据质量；\n3. 统一指标口径。\n任职要求：\n1. 精通 SQL 与维度建模；\n2. 熟悉 Spark / Hive；\n3. 金融行业经验优先。"},
    {"id": 9, "title": "Java 后端开发", "company": "某电商平台", "city": "杭州", "degree": "本科", "direction": "后端",
     "skills": ["Java", "Spring Boot", "MySQL", "Redis", "消息队列"],
     "jd": "岗位职责：\n1. 订单/支付核心链路开发；\n2. 高并发性能优化；\n3. 保障系统稳定性。\n任职要求：\n1. 熟悉 Java 与 Spring Boot；\n2. 熟悉 MySQL、Redis；\n3. 分布式系统经验优先。"},
    {"id": 10, "title": "Python 后端工程师", "company": "某 SaaS 公司", "city": "远程", "degree": "本科", "direction": "后端",
     "skills": ["Python", "FastAPI", "MySQL", "Redis", "Docker"],
     "jd": "岗位职责：\n1. SaaS 平台后端接口开发；\n2. 数据模型与任务调度；\n3. 服务容器化。\n任职要求：\n1. 熟悉 FastAPI / Flask；\n2. 熟悉 MySQL 与 Redis；\n3. 了解 Docker 与 Linux。"},
    {"id": 11, "title": "Go 后端开发", "company": "某云服务公司", "city": "北京", "degree": "本科", "direction": "后端",
     "skills": ["Go", "MySQL", "Redis", "Kubernetes", "微服务"],
     "jd": "岗位职责：\n1. 云平台控制面服务开发；\n2. 微服务治理与可观测性；\n3. 支撑大规模集群。\n任职要求：\n1. 熟悉 Go 与并发编程；\n2. 熟悉 Kubernetes；\n3. 云原生经验优先。"},
    {"id": 12, "title": "前端工程师（React）", "company": "某 SaaS 公司", "city": "上海", "degree": "本科", "direction": "前端",
     "skills": ["React", "TypeScript", "CSS", "Git"],
     "jd": "岗位职责：\n1. 中后台系统前端开发；\n2. 与设计、后端协作交付；\n3. 组件库建设与性能优化。\n任职要求：\n1. 熟悉 React 与 TypeScript；\n2. 熟悉 CSS 布局；\n3. 组件库经验优先。"},
    {"id": 13, "title": "全栈开发工程师", "company": "某创业团队", "city": "深圳", "degree": "本科", "direction": "前端",
     "skills": ["Python", "React", "MySQL", "Docker", "Git"],
     "jd": "岗位职责：\n1. 独立完成小型产品前后端；\n2. 参与需求评审与技术选型；\n3. 上线部署与维护。\n任职要求：\n1. 熟悉 Python 后端与 React；\n2. 了解 Docker；\n3. 0 到 1 产品经验优先。"},
    {"id": 14, "title": "AI 产品经理", "company": "某大厂", "city": "北京", "degree": "本科", "direction": "产品",
     "skills": ["Prompt", "数据分析", "需求分析", "Axure"],
     "jd": "岗位职责：\n1. AI 功能需求定义与优先级；\n2. 设计 Prompt 与评测方案；\n3. 协调算法、工程、设计交付。\n任职要求：\n1. 理解大模型能力边界；\n2. 有数据分析与需求文档能力；\n3. AI 产品落地经验优先。"},
    {"id": 15, "title": "产品经理（AI 方向）", "company": "某教育科技", "city": "杭州", "degree": "本科", "direction": "产品",
     "skills": ["需求分析", "数据分析", "Prompt", "用户调研"],
     "jd": "岗位职责：\n1. AI 学习产品功能规划；\n2. 用户调研验证需求；\n3. 版本迭代与数据复盘。\n任职要求：\n1. B 端或 C 端产品经验；\n2. 熟悉数据分析方法；\n3. 持续关注 AI 应用。"},
    {"id": 16, "title": "AI 解决方案工程师", "company": "某云厂商", "city": "上海", "degree": "本科", "direction": "AI 应用",
     "skills": ["Python", "Prompt", "方案设计", "客户沟通"],
     "jd": "岗位职责：\n1. 客户场景方案设计与演示；\n2. 编写技术方案文档；\n3. 支持交付落地。\n任职要求：\n1. 熟悉大模型应用与 Prompt；\n2. 良好的沟通与文档能力；\n3. 可短期出差。"},
    {"id": 17, "title": "AI 交付工程师", "company": "某 AI 服务商", "city": "北京", "degree": "大专", "direction": "AI 应用",
     "skills": ["Python", "Linux", "Prompt", "Docker"],
     "jd": "岗位职责：\n1. 客户现场部署与调试；\n2. 排查线上问题；\n3. 收集反馈推动改进。\n任职要求：\n1. 熟悉 Linux 常用命令；\n2. 会 Python 脚本；\n3. 现场支持经验优先。"},
    {"id": 18, "title": "测试开发工程师", "company": "某互联网公司", "city": "成都", "degree": "本科", "direction": "测试",
     "skills": ["Python", "自动化测试", "Linux", "Git"],
     "jd": "岗位职责：\n1. 服务端接口自动化测试；\n2. 建设用例库与 CI；\n3. 质量度量与复盘。\n任职要求：\n1. 熟悉 Python 与测试框架；\n2. 熟悉 Linux 与 Git；\n3. 性能测试经验优先。"},
    {"id": 19, "title": "运维开发工程师", "company": "某云服务公司", "city": "北京", "degree": "本科", "direction": "运维",
     "skills": ["Python", "Linux", "Shell", "Docker", "Kubernetes"],
     "jd": "岗位职责：\n1. 自动化运维平台开发；\n2. 监控告警与故障自愈；\n3. 容量规划与成本优化。\n任职要求：\n1. 熟悉 Linux 与 Shell；\n2. 会 Python 开发工具；\n3. 熟悉容器与编排。"},
    {"id": 20, "title": "AI 应用开发（实习·远程）", "company": "某海外创业团队", "city": "远程", "degree": "大专", "direction": "AI 应用",
     "skills": ["Python", "Prompt", "LangChain", "Git"],
     "jd": "岗位职责：\n1. AI 工具类产品功能开发；\n2. 编写 Prompt 并做效果对比；\n3. 协助文档与技术博客。\n任职要求：\n1. 熟悉 Python 基础；\n2. 对大模型应用有热情；\n3. 每周投入 20 小时以上。"},
]

ALL_SKILLS = sorted({s for j in JOBS for s in j["skills"]})

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
                {"role": "user", "content": text},
            ],
            temperature=0,
        )
        data = json.loads(r.choices[0].message.content)
        # 模型可能给中文键，做一次兜底映射
        if "姓名" in data and "name" not in data:
            data["name"] = data["姓名"]
        if "年限" in data and "years" not in data:
            data["years"] = data["年限"]
        if "技能" in data and "skills" not in data:
            data["skills"] = data["技能"]
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
    """返回 (匹配度, 已掌握, 缺失)；先统一小写，避免大小写不匹配。"""
    need_map = {s.lower(): s for s in job["skills"]}
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
            else:
                with st.spinner("解析中……"):
                    st.session_state.parsed = llm_extract(resume_text)
                if st.session_state.parsed is None:
                    st.error("解析失败，已退回规则匹配")
    with col_b:
        if st.button("清空", use_container_width=True):
            st.session_state.parsed = None
            st.rerun()

    # 取技能：优先用 AI 结果，没有就用规则
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
st.caption("筛选岗位 · 查看 JD · 对照简历找差距")

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
