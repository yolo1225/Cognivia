from __future__ import annotations

import re
import shutil
import sys
import zipfile
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentType
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}

TUTORING_BLOCK = r"""
\subsection{基于资源证据与多轮反馈的交互导学机制}

系统已经实现独立的交互导学 Agent，而非仅在页面收集“太难”“太简单”等标签。
学习者围绕当前讲义、实操指南或测验发起会话后，导学服务将当前资源正文、关联知识点、Candidate 来源片段和最近十轮对话组织为受控上下文；模型负责识别反馈语义并生成候选回答，确定性教学策略负责决定是否追问、解释、复核或创建后续任务。语言模型不能直接修改画像，也不能自行决定发布挑战资源。

动态追问采用逐轮升级策略。首次明确的困难反馈只定位学习者卡在概念理解、操作过程还是结果验证，并返回针对性提示，不更新画像、不创建生成任务；同一困难在后续轮次仍未解决时，系统才触发带来源的补救解释。对于“太简单”，若缺少已确认的计分题或行为证据，系统先提出迁移问题或小任务验证掌握；只有受控证据满足置信度门槛后，才允许创建挑战任务。对于“内容有误”，系统优先重新检索来源并触发审核，且不把资源问题归因于学习者能力。

该机制属于受控动态追问与渐进式导学：它已经实现多轮历史、困难定位、资源约束回答、掌握验证和补救升级，但不将自身表述为通用苏格拉底教学引擎。每轮会话均保存学习者消息、导学回复、反馈意图、推荐动作、证据引用和 Agent Run 摘要，使答辩演示能够回放“提问—定位—提示—验证—后续决策”的真实链路。
"""

GENERATION_BLOCK = r"""
\subsection{个性化资源生成与结构约束}

生成 Agent 接收画像快照、学习目标、目标难度、薄弱知识以及检索 Agent 返回的 Candidate Chunk，在同一证据边界内生成讲义、实操指南和分阶测验。画像信息不只改变措辞：能力层级决定讲解深度与任务复杂度，薄弱知识决定内容重点，目标难度约束步骤颗粒度、案例复杂度和题目认知层级。

三类资源采用不同的结构契约。讲义组织概念、关联知识、示例与要点总结；实操指南组织可执行步骤、依据、预期结果和异常处理；分阶测验从正式活动题库选择与知识范围及目标难度匹配的题目，并保留答案与解析。每项资源同时输出知识来源、证据引用和可审核的原子声明，不能引用检索结果之外的专业事实。

生成结果先经过 Pydantic 契约和业务规则校验，再交由审核 Agent 处理，生成成功不等于允许发布。审核要求修订时，系统沿用原任务证据边界，仅替换未通过的资源、题目位置或字段，并保留已通过内容及其审核记录。
"""

PROFILE_COMPARISON_BLOCK = r"""
\subsection{差异化画像与案例设计}

三类脱敏合成画像分别具有不同教育背景、专业方向、实践经验和能力水平，用于比较对应的资源策略与反馈动作。

\begingroup
\centering
\small
\begin{longtable}{|p{0.11\textwidth}|p{0.15\textwidth}|p{0.15\textwidth}|p{0.25\textwidth}|p{0.15\textwidth}|}
\hline
\bfseries 画像 & \bfseries 背景与能力特征 & \bfseries 主要薄弱点 & \bfseries 个性化资源策略 & \bfseries 反馈后动作 \\ \hline
初学者 & 计算机专业本科在读，0 年相关经验，五维均值 45 & AI 应用概览、Python API 基础 & 基础概念、最小调用步骤与结果核验 & 定位困难并提供补救解释 \\ \hline
进阶学习者 & 软件工程本科，1 年相关经验，五维均值 60 & HTTP REST 基础、Git 协作 & 接口实践、配置比较与错误归因 & 错题修正后进行独立掌握验证 \\ \hline
高阶学习者 & 人工智能硕士，3 年相关经验，五维均值 80 & Prompt 基础、上下文设计 & 设计权衡、复杂约束与综合任务 & 验证掌握后生成挑战任务 \\ \hline
\end{longtable}
\endgroup
"""

PERSONALIZATION_METHOD_BLOCK = r"""
\subsection{个性化差异验证方法}

验证采用控制变量法：同一组比较中保持岗位任务、领域知识版本、来源白名单、请求资源类型和审核门槛不变，仅改变画像背景、五维能力、薄弱知识及正式学习证据。系统输出必须在目标难度、检索知识范围、讲义深度、实操步骤、测验认知层级和反馈后动作上形成可追踪差异；仅改变称呼、语气或篇幅不计为个性化。

同时设置不变量约束：三类画像均须满足相同的事实准确性、来源追溯、核心知识覆盖和原子发布规则，不得以降低质量标准换取表面差异。验证记录通过画像决策、召回 Chunk、资源结构、审核结论和反馈动作进行逐项比对；正式质量结果统一在 4.6 节报告。
"""

CHAPTER_SIX_BLOCK = r"""
\section{拓展改进与应用价值}

\subsection{拓展改进计划}

以下能力属于后续拓展方向，当前版本不作为已实现功能：一是增加语音、视频等多模态学习材料与作答方式；二是在数据规模和质量满足条件后研究领域模型微调与小模型蒸馏；三是引入答题时长、路径停留等更多行为证据；四是细化一道题中多个知识点的贡献权重；五是识别主观题中的具体错误模式，以提高诊断和推荐精度。

\subsection{应用价值}

在教育培训中，系统可用于高校实训、职业教育和技术课程更新，为不同基础学习者生成带来源、经审核且难度适配的讲义、实操指南和测验，并向教师提供能力结构、知识盲区和学习路径依据。

在企业内训中，系统可围绕组织内部技术规范、产品文档和岗位标准构建受控知识包，支持新员工培养、在岗技能升级和岗位转岗培训。内容更新后可通过关系传播、索引重建和路径刷新缩短培训材料维护周期。

在技术产品层面，可将领域知识导入、Candidate 检索、多 Agent 生成审核、交互导学和离线评测封装为平台能力或集成接口。领域迁移边界以 3.4 节的三组闭环验证为依据，不将小规模验证外推为未经评测的行业结论。

在社会价值层面，来源追踪、质量阻断和学习差异适配有助于降低错误技术内容进入教学实践的风险，并让高质量专业训练资源更易复用。项目不以缺少数据支撑的市场规模或效益数字作为价值证明。
"""


def esc(text: str) -> str:
    text = text.replace("\u00a0", " ")
    mapping = {
        "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
        "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
        "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    }
    return "".join(mapping.get(ch, ch) for ch in text)


def math_text(node) -> str:
    return "".join(node.itertext()).strip()


def omml(node) -> str:
    tag = node.tag.rsplit("}", 1)[-1]
    if tag in {"oMath", "oMathPara", "e", "num", "den", "sub", "sup"}:
        return "".join(omml(c) for c in node)
    if tag == "r":
        value = math_text(node)
        return value.replace("×", r"\times ").replace("∑", r"\sum ")
    if tag == "f":
        num = node.find("m:num", NS)
        den = node.find("m:den", NS)
        return rf"\frac{{{omml(num)}}}{{{omml(den)}}}"
    if tag == "sSub":
        base, sub = node.find("m:e", NS), node.find("m:sub", NS)
        return rf"{omml(base)}_{{\mathrm{{{omml(sub).replace('_', r'\_')}}}}}"
    if tag == "sSup":
        base, sup = node.find("m:e", NS), node.find("m:sup", NS)
        return rf"{omml(base)}^{{{omml(sup)}}}"
    if tag == "sSubSup":
        base = node.find("m:e", NS)
        return rf"{omml(base)}_{{{omml(node.find('m:sub', NS))}}}^{{{omml(node.find('m:sup', NS))}}}"
    if tag == "nary":
        char = node.find("m:naryPr/m:chr", NS)
        op = r"\sum" if char is None or char.get(qn("m:val")) == "∑" else math_text(char)
        sub, sup, body = node.find("m:sub", NS), node.find("m:sup", NS), node.find("m:e", NS)
        return rf"{op}_{{{omml(sub)}}}^{{{omml(sup)}}} {omml(body)}"
    if tag == "d":
        body = node.find("m:e", NS)
        return rf"\left({omml(body)}\right)"
    return "".join(omml(c) for c in node)


def normalize_formula(formula: str) -> str:
    formula = formula.replace("%", r"\%")
    if formula.startswith("score=0.50"):
        formula = r"S_{\mathrm{retrieval}}=0.50S_{\mathrm{route}}+0.35S_{\mathrm{similarity}}+0.15S_{\mathrm{difficulty}}"
    formula = formula.replace(
        "difficulty_score=max(0,1-0.20\\times |d_{\\mathrm{chunk}}-d_{\\mathrm{target}}|)",
        r"S_{\mathrm{difficulty}}=\max\left(0,1-0.20\left|d_{\mathrm{chunk}}-d_{\mathrm{target}}\right|\right)",
    )
    formula = formula.replace(
        "weakness_level=clamp(1,5,round((1-M)\\times 5))",
        r"L_{\mathrm{weakness}}=\operatorname{clamp}\left(1,5,\operatorname{round}\left((1-M)\times 5\right)\right)",
    )
    return formula


def iter_blocks(parent):
    root = parent.element.body if isinstance(parent, DocumentType) else parent._tc
    for child in root.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, parent)
        elif child.tag == qn("w:tbl"):
            yield Table(child, parent)


def paragraph_images(paragraph: Paragraph, doc: DocumentType, assets: Path, counter: list[int]):
    results = []
    for blip in paragraph._p.xpath(".//a:blip"):
        rid = blip.get(qn("r:embed"))
        if not rid:
            continue
        part = doc.part.related_parts[rid]
        suffix = Path(part.partname).suffix or ".png"
        counter[0] += 1
        name = f"figure-{counter[0]:02d}{suffix}"
        (assets / name).write_bytes(part.blob)
        results.append(name)
    return results


def table_latex(table: Table) -> str:
    rows = []
    max_cols = max((len(r.cells) for r in table.rows), default=1)
    col_width = max(0.12, 0.86 / max_cols)
    spec = "|" + (rf">{{\raggedright\arraybackslash}}p{{{col_width:.3f}\textwidth}}|" * max_cols)
    for ri, row in enumerate(table.rows):
        cells = []
        for cell in row.cells[:max_cols]:
            value = " ".join(p.text.strip() for p in cell.paragraphs if p.text.strip())
            value = esc(value).replace("\n", r" ")
            cells.append((r"\bfseries " if ri == 0 else "") + value)
        cells += [""] * (max_cols - len(cells))
        rows.append(" & ".join(cells) + r" \\ \hline")
    return "\n".join([
        r"\begingroup", r"\centering", r"\small", rf"\begin{{longtable}}{{{spec}}}",
        r"\hline", *rows, r"\end{longtable}", r"\endgroup"
    ])


def style_level(paragraph: Paragraph):
    name = (paragraph.style.name or "").lower()
    text = paragraph.text.strip()
    if re.match(r"^[一二三四五六七八九十]+、", text):
        return 1
    if re.match(r"^\d+\.\d+(?:\s|、)", text):
        return 2
    if "heading 1" in name or "标题 1" in name:
        return 1
    if "heading 2" in name or "标题 2" in name:
        return 2
    if "heading 3" in name or "标题 3" in name:
        return 3
    return None


def replace_subsection(blocks: list[str], title: str, replacement: list[str]) -> None:
    marker = rf"\subsection{{{title}}}"
    start = blocks.index(marker)
    end = next(
        (i for i in range(start + 1, len(blocks)) if blocks[i].startswith((r"\subsection{", r"\section{"))),
        len(blocks),
    )
    blocks[start:end] = replacement


def refine_blocks(blocks: list[str]) -> list[str]:
    replace_subsection(blocks, "问题背景", [
        r"\subsection{问题背景}",
        "人工智能应用开发等垂直领域具有知识更新快、工程细节多和学习起点差异大的特点。静态课程难以同时适配不同基础与学习节奏；通用大模型生成的 API 用法、检索设计、评测口径和部署约束又可能缺少可靠依据，错误内容一旦进入实训会直接影响操作结果。因此，本项目聚焦三个问题：领域知识如何持续更新、资源如何按学习差异生成、生成结果如何在发布前得到可追溯验证。",
    ])
    replace_subsection(blocks, "典型岗位任务与系统应用场景", [
        r"\subsection{典型岗位任务与系统应用场景}",
        "系统以人工智能应用开发实训为主验证领域，将知识学习组织为三类可执行、可检查的岗位任务。",
        "岗位任务一是企业技术文档 RAG 知识库开发，覆盖知识切分、向量检索、召回验证和来源追踪，验收产物包括配置记录、检索结果、召回分析和来源映射。岗位任务二是多 Agent 应用编排与失败恢复，覆盖节点职责、结构化交接、检查点、局部修订和失败阻断，验收产物包括状态机、Agent Run、消息记录和任务终态。岗位任务三是大模型应用质量评测，覆盖案例构造、事实支持、难度匹配、知识覆盖和结果复现，验收产物包括案例集、审核声明、质量报告与失败归因。",
        "三个任务复用诊断、画像、检索、生成、审核与反馈能力，但分别强调知识证据、工程编排和质量评测。三类学习者的具体差异统一在 4.2 节比较。学习反馈由已实现的交互导学机制处理，具体策略见 5.11 节。",
    ])

    replace_subsection(blocks, "业务闭环", [
        *blocks[blocks.index(r"\subsection{业务闭环}"):next(i for i in range(blocks.index(r"\subsection{业务闭环}") + 1, len(blocks)) if blocks[i].startswith(r"\section{"))],
        "学情报告已实现能力结构、知识盲区与优先级、资源难度匹配和个性化学习路径可视化。资源难度匹配图读取真实资源难度等级与审核适配度，分别以柱形和折线呈现，并标示 85\\% 通过阈值；完整界面由 PPT 与现场演示展示，技术文档不重复放置界面截图。",
    ])

    replace_subsection(blocks, "第二领域小规模迁移验证", [
        r"\subsection{第二领域小规模迁移验证}",
        "项目以智能制造独立数据包验证领域迁移能力，替换领域定义、知识目录、知识关系、正式题库、三类合成画像与来源材料，并复用原有 Agent 主图、V10 契约、任务状态、审核门禁、反馈决策、API 和前端工作流。迁移不修改核心编排代码，领域差异通过数据与配置进入系统。",
        "初学者首次生成、进阶学习者错误反馈复核和高阶学习者进阶挑战三组迁移闭环均已通过。验证覆盖任务身份一致、主副审核角色、结构化交接、三类资源发布、来源与质量元数据、错误反馈不直接修改画像及挑战任务掌握证据。由此可见，替换领域知识包、关系、能力标准和题库后，系统能够复用编排、生成、审核和反馈机制。",
    ])

    replace_subsection(blocks, "测试设计", [r"\subsection{测试设计与指标口径}"] + blocks[
        blocks.index(r"\subsection{测试设计}") + 1:blocks.index(r"\subsection{差异化画像与测试对象设计}")
    ])
    start = blocks.index(r"\subsection{差异化画像与测试对象设计}")
    end = blocks.index(r"\subsection{50 例场景覆盖与用例组织}")
    blocks[start:end] = [PROFILE_COMPARISON_BLOCK, PERSONALIZATION_METHOD_BLOCK]
    blocks[blocks.index(r"\subsection{50 例场景覆盖与用例组织}")] = r"\subsection{50例场景覆盖与用例组织}"
    blocks[blocks.index(r"\subsection{live formal 执行流程与数据留痕}")] = r"\subsection{live formal执行流程与数据留痕}"
    blocks[blocks.index(r"\subsection{指标计算与测试结果}")] = r"\subsection{正式评测结果}"
    result_anchor = next(
        i for i, block in enumerate(blocks)
        if block.startswith("正式报告采用质量指标与运行结果双口径")
    )
    blocks[result_anchor] = (
        "正式报告采用质量指标与运行结果双口径。50 个案例均形成可判定结果，其中 48 个任务完成并发布，任务成功率为 96\\%；"
        "V4-EVAL-004 与 V4-EVAL-022 在两轮局部修订后仍未通过审核，最终状态为 revision\\_exhausted，相关学习包被质量门禁阻断且未向学习者展示。"
        "幻觉率为 $4/314=1.27\\%$；难度匹配的 45 个适用案例全部通过，即 $45/45=100\\%$，另有 5 个案例按审核规则标记为不适用且不进入分母；核心知识覆盖率为 $75/75=100\\%$。"
    )

    replace_subsection(blocks, "证据约束与原子发布", [
        r"\subsection{证据约束与原子发布}",
        "生成内容必须限定在可追溯来源与检索证据边界内；资源发布采用整包原子策略，三类请求资源及其来源、审核结果和路径节点完整后才转为学习者可见。具体的双模型复核、补检索、仲裁与指标算法集中在 5.10 节说明。",
    ])
    generation_marker = r"\subsection{学情画像、难度定标与学习路径算法}"
    blocks.insert(blocks.index(generation_marker), GENERATION_BLOCK.strip())
    replace_subsection(blocks, "双模型审核、仲裁与质量门禁算法", [
        r"\subsection{双模型审核、仲裁与质量门禁算法}",
        next(block for block in blocks if "assets/figure-07" in block),
        "图7 审核决策流程图",
        "主审核模型与副审核模型分别检查事实准确性、来源可追溯性、难度匹配和核心知识覆盖。两路事实与来源结论必须同时通过；当总分差异超过 10 分，或一路通过而另一路不通过时，系统按受影响知识点重新检索来源并再次审核。若分歧仍存在，则将相关声明标记为 unresolved，仅把受影响资源送入局部修订。",
        "复核后的原子声明状态为 supported、contradicted、evidence\\_insufficient 或 unresolved。质量门禁按 4.6 节公式计算幻觉率、难度匹配率与核心知识覆盖率，并检查请求资源完整性；达到两轮修订上限仍不通过时整包失败，未解决资源不向学习者发布。",
    ])
    feedback_marker = r"\subsection{反馈决策、局部修订与原子发布}"
    blocks.insert(blocks.index(feedback_marker), TUTORING_BLOCK.strip())
    api_title = r"\subsection{服务接口、SSE 与受控可观测性设计}"
    api_start = blocks.index(api_title)
    api_end = next(i for i in range(api_start + 1, len(blocks)) if blocks[i].startswith(r"\subsection{"))
    blocks.insert(api_end, "报告接口聚合画像、薄弱知识、已审核资源和学习路径，前端使用 ECharts 渲染能力结构、知识盲区、资源难度匹配和路径视图。")
    replace_subsection(blocks, "反馈决策、局部修订与原子发布", [
        r"\subsection{反馈决策、局部修订与原子发布}",
        "交互导学输出结构化反馈意图后，决策服务结合当前任务、正式学习证据和资源审核状态选择后续动作。主观反馈不直接覆盖画像；错误类反馈进入资源复核，补救或挑战动作依据 5.11 节形成的受控证据触发。",
        "需要修订时，系统仅重检索受影响知识点并重生成存在问题的字段或资源，保留已通过内容及其审核记录。完成局部复核后，发布服务重新校验资源集合、来源映射和学习路径的一致性，再执行整包发布或阻断。",
        next(block for block in blocks if "assets/figure-08" in block),
        "图8 学习反馈决策树",
    ])

    chapter_six = blocks.index(r"\section{拓展改进与应用价值}")
    blocks[chapter_six:] = [CHAPTER_SIX_BLOCK]
    blocks = [
        block.replace(r"initial\_generation", r"initial\_\allowbreak generation")
        .replace(r"feedback\_revision", r"feedback\_\allowbreak revision")
        .replace("支持 Markdown、Word、PDF 等文档形式", "支持 PDF、Markdown、TXT 等文档形式")
        for block in blocks
    ]
    return blocks


def build(source: Path, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    assets = out_dir / "assets"
    if assets.exists():
        shutil.rmtree(assets)
    assets.mkdir()
    doc = Document(source)
    blocks = []
    image_count = [0]
    first_heading_seen = False
    skipping_static_toc = False

    for block in iter_blocks(doc):
        if isinstance(block, Table):
            blocks.append(table_latex(block))
            continue
        p = block
        text = p.text.strip()
        equations = p._p.xpath(".//m:oMath")
        images = paragraph_images(p, doc, assets, image_count)
        level = style_level(p)
        if text.startswith("关键词："):
            blocks.append(esc(text) + "\n")
            skipping_static_toc = True
            continue
        if text == "目录":
            skipping_static_toc = True
            continue
        if skipping_static_toc:
            if level == 1 and "\t" not in text and not re.search(r"\s\d+$", text):
                skipping_static_toc = False
            else:
                continue
        if text == "摘要":
            first_heading_seen = True
            blocks.append(r"\section*{摘要}\addcontentsline{toc}{section}{摘要}")
            continue
        if level and text:
            first_heading_seen = True
            clean = re.sub(r"^[一二三四五六七八九十]+、\s*", "", text) if level == 1 else re.sub(r"^\d+\.\d+(?:\s|、)*", "", text)
            cmd = "section" if level == 1 else "subsection" if level == 2 else "subsubsection"
            blocks.append(rf"\{cmd}{{{esc(clean)}}}")
        elif equations:
            for eq in equations:
                blocks.append("\\[\n" + normalize_formula(omml(eq)) + "\n\\]")
        elif images:
            for image in images:
                blocks.append("\n".join([r"\begin{figure}[H]", r"\centering", rf"\includegraphics[width=0.90\textwidth,height=0.72\textheight,keepaspectratio]{{assets/{image}}}", r"\end{figure}"]))
        elif text and first_heading_seen:
            if text.startswith(("", "•", "·")):
                blocks.append(r"\begin{itemize}\item " + esc(text.lstrip("•· ")) + r"\end{itemize}")
            else:
                blocks.append(esc(text) + "\n")

    blocks = refine_blocks(blocks)
    title = r"云川智汇\\[0.5em]{\Large 多智能体协同驱动的领域知识个性化学习平台}"
    preamble = rf"""\documentclass[12pt,a4paper]{{ctexart}}
\usepackage[left=2.0cm,right=2.0cm,top=2.2cm,bottom=2.0cm]{{geometry}}
\usepackage{{amsmath,amssymb,booktabs,array,longtable,graphicx,float,xcolor,fancyhdr,hyperref,setspace}}
\definecolor{{CogniviaBlue}}{{HTML}}{{1F4E79}}
\definecolor{{CogniviaText}}{{HTML}}{{172033}}
\hypersetup{{colorlinks=true,linkcolor=CogniviaBlue,urlcolor=CogniviaBlue}}
\setstretch{{1.32}}
\setlength{{\parindent}}{{2em}}
\setlength{{\parskip}}{{0.35em}}
\setlength{{\headheight}}{{15pt}}
\setcounter{{tocdepth}}{{2}}
\ctexset{{section={{format=\Large\bfseries\color{{CogniviaBlue}}}},subsection={{format=\large\bfseries}},subsubsection={{format=\normalsize\bfseries}}}}
\pagestyle{{fancy}}
\fancyhf{{}}
\fancyhead[L]{{\small 云川智汇 · 多智能体协同驱动的领域知识个性化学习平台}}
\fancyfoot[C]{{\small Cognivia\quad |\quad 第 \thepage 页}}
\renewcommand{{\headrulewidth}}{{0.4pt}}
\renewcommand{{\arraystretch}}{{1.35}}
\begin{{document}}
\begin{{titlepage}}
\centering
\vspace*{{3cm}}
{{\Huge\bfseries\color{{CogniviaBlue}} {title}\par}}
\vspace{{1.2cm}}
{{\LARGE 技术设计方案\par}}
\vfill
{{\large 作者：徐何乐、陈启铭、吴渊、孙振威\par}}
\vspace{{0.5cm}}
{{\large 指导教师：陈伟斌、叶洁琼\par}}
\vspace{{0.5cm}}
{{\large 温州大学计算机与人工智能学院\par}}
\vspace{{1.5cm}}
{{\large 2026 年 9 月\par}}
\end{{titlepage}}
"""
    ending = "\n\\end{document}\n"
    first_section = next(
        (index for index, block in enumerate(blocks) if block.startswith(r"\section{")),
        len(blocks),
    )
    front_matter = blocks[:first_section]
    main_matter = blocks[first_section:]
    content = (
        preamble
        + "\n\n".join(front_matter)
        + "\n\n\\clearpage\n\\tableofcontents\n\\clearpage\n\n"
        + "\n\n".join(main_matter)
        + ending
    )
    (out_dir / "Cognivia_技术文档附录_重组修订版.tex").write_text(content, encoding="utf-8")
    print(f"Wrote {len(blocks)} blocks, {image_count[0]} images")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: docx_to_latex.py SOURCE.docx OUTPUT_DIR")
    build(Path(sys.argv[1]), Path(sys.argv[2]))
