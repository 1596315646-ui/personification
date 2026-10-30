#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人类密度写作 · 验收器

它只做一件事：把能数的东西数出来。它不判断文章好不好。

为什么不做整体评分：SLOP 论文（arXiv 2509.19163）实测 GPT-5 判断文本是否为 slop
的 Cohen's kappa = 0.01，基本等于瞎蒙。任何「像不像 AI」的自动总分都不可信。
所以这里只报可复核的计数，判断留给人。

能查的（硬指标）：
  1. 事实密度          —— 每 300 中文字的具体事实数
  2. 数字自洽          —— 文中数字能否加总/对上（半自动，需人工确认提示）
  3. 谄媚信号          —— 四类句子
  4. 假中立            —— 辩证式中立套话
  5. 零风险表述        —— 高频空话模板
  6. 留白动作          —— 四种「不知道」的正确写法命中情况

查不了的（如实告知）：
  - 可替换性测试（需要语义理解，得人来）
  - 事实是否真的可查（需要联网核实）
  - 结构是否为内容服务（需要读完整篇）

用法：
    python check.py 稿子.md
    python check.py 稿子.md --genre 纪实
    python check.py 稿子.md --json
    python selftest.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
CJK = r"[\u4e00-\u9fff]"

# ---------------------------------------------------------------- 文体阈值
# 2026-10-29 两轮标定后的最终结论：**只有中文短篇一类敢给阈值。**
#
# 为什么这么少：
#   1. 中文侧只有 294 篇现代中文短篇是稳定测量（口径 = count_facts()，两轮都 2.37）
#   2. 英文侧找不到稳定口径 —— 「裸数字算不算事实」这一个选择，就让
#      同一批文本的密度差 2.8 倍（技术文档 8.23 vs 3.22，学术 7.12 vs 1.71）。
#      口径不稳，据它定的阈值就不能用。三条英文阈值已全部撤回。
#   3. 其余体裁人类样本 n≤3，或根本没有中文样本。
#
# 因此：除短篇/散文外，一律 min=None，只报数不划线。
GENRES = {
    "短篇": {"min": 1.5, "n": 294, "p10": 1.55, "conf": "标定",
             "note": "ZH 现代中文短篇 294 篇（中国作家网）。实测 P10=1.55，"
                     "取 1.5 → 93.2% 的人类文本过线。两轮独立测量一致"},
    "散文": {"min": 1.5, "n": 294, "p10": 1.55, "conf": "标定",
             "note": "借用中文短篇分布（同属叙事类）"},

    "纪实": {"min": 2.7, "n": 3, "p10": 2.72, "conf": "观察",
             "note": "ZH 纪实·现代 3 篇（中国作家网《纪实专栏》，清洗网页头后）"
                     "实测 2.72 / 4.25 / 5.81，取 min=2.7。n 只 3 篇，"
                     "用「见过的最低人类样本」而不是 P10。原设 ≥6，偏高约 40%，已下调"},

    # ---- 以下只报数：口径不可靠或样本不足 ----
    "纪实·文言": {"min": None, "n": 3, "p10": None, "conf": "不可测",
                  "note": "文言量词（里/丈/石/斗/步）不在计数口径里，"
                          "补上后密度涨 89%（1.93→3.64）。测不准，不给线"},
    "书信": {"min": None, "n": 3, "p10": None, "conf": "偏低置信",
             "note": "只有曾国藩 3 封（道光年间），实测 4.45—9.14。"
                     "古文家书事实密度高，现代书信可能低得多，不敢外推"},
    "科普": {"min": None, "n": 3, "p10": None, "conf": "不可测",
             "note": "宋应星 / 沈括，补上文言量词后涨 38%。口径未覆盖，测不准"},
    "文学评论": {"min": None, "n": 3, "p10": None, "conf": "不可测",
             "note": "刘勰 / 袁枚，补上文言量词后涨 27%。口径未覆盖"},
    "评论": {"min": None, "n": 1, "p10": 0.17, "conf": "样本不足",
             "note": "只有奥威尔《政治与英语》1 篇，密度 0.17。"
                     "最好的论说文可以近乎零数字，不给阈值"},
    "公文": {"min": None, "n": 2, "p10": 0.00, "conf": "样本不足",
             "note": "这类看对象明确与权责清楚，不看密度"},
    "学术": {"min": None, "n": 4, "p10": None, "conf": "不可测",
             "note": "只有英文样本，且英文口径不稳（宽 7.12 / 窄 1.71）"},
    "技术": {"min": None, "n": 10, "p10": None, "conf": "不可测",
             "note": "只有英文样本，英文口径不稳（宽 8.23 / 窄 3.22）。"
                     "规范类与指南类内部差 20 倍"},
    "演讲": {"min": None, "n": 4, "p10": None, "conf": "不可测",
             "note": "只有英文样本，英文口径不稳（宽 1.14 / 窄 0.38）"},
}

# ---------------------------------------------------------------- 事实计数
CN = "零一二三四五六七八九十百千万两"
# 「一」作虚词的常见搭配，命中则不计
YI_FALSE = re.compile(r"(?:方面|致|律|起|般|直|些|切|旦|览|并|再|定|样|种|来|是|个|部分|系列|体|贯|向|如|概|同|共|时|次性|味|流|线)")

FACT_PATTERNS = [
    # 数字 + 量词/单位
    ("num", rf"[{CN}\d]{{1,6}}(?=(?:个|人|年|月|日|号|点|天|周|小时|分钟|秒|次|名|块|万元|万|亿|元|倍|成|层|条|项|页|篇|本|件|台|部|站|字|公斤|公里|度|岁|家|位|份|场|轮|期))"),
    # 阿拉伯数字（排除小数点和列表编号）
    ("ar", r"(?<![\d.])\d{1,6}(?:\.\d+)?(?![.、\d])"),
    # 百分比
    ("pct", r"\d+(?:\.\d+)?\s*%"),
    # 年份
    ("yr", r"(?:19|20)\d{2}\s*年"),
    # 时刻
    ("tm", rf"(?:上午|下午|晚上|凌晨|中午)[{CN}\d]{{1,3}}(?:点|时)"),
]

LIST_MARK = re.compile(r"^(?:[一二三四五六七八九十]+[、.]|\d+[.、)）]|（[一二三四五六七八九十\d]+）)\s*")


def count_facts(text: str) -> list[tuple[str, str]]:
    """返回 [(类型, 命中串)]。口径与 sources/corpus-findings.md 一致。

    两处曾经算错的坑，这里都处理了：
      1. 只匹配 \\d+ 会漏「开了两个人」「五个小时」——中文数字必须计
      2. 不排除列表编号会把「1. 2. 3.」算成事实；「一方面」里的一不该计
    """
    spans = []  # (start, end, kind, tok)
    for kind, pat in FACT_PATTERNS:
        for m in re.finditer(pat, text):
            s, e = m.start(), m.end()
            tok = m.group(0)

            # 排除行首列表编号（1. / 2、 / 一、/（三））
            ls = text.rfind("\n", 0, s) + 1
            if not text[ls:s].strip() and LIST_MARK.match(text[ls:e + 1]):
                continue

            # 排除序数：「第一点」「第三条」「第二章」——这是排序不是数量
            if s > 0 and text[s - 1] == "第":
                continue

            # 排除「一」作虚词（一方面/一致/一律/一个…）
            # 注意：这条只能对「一」生效。早先把 len(tok)==1 也排除，
            # 结果把「开掉了两个人」的「两」也误杀了。
            if tok == "一":
                after = text[e:e + 3]
                if YI_FALSE.match(after):
                    continue

            spans.append((s, e, kind, tok))

    # 去重按「位置重叠」而不是按「值」——
    # 按值去重会把「三件事……这三条成立……这三条不成立」里的重复计数删掉，
    # 那是三处真实事实，不该合并。
    spans.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    out, last_end = [], -1
    for s, e, k, v in spans:
        if s < last_end:
            continue
        out.append((k, v))
        last_end = e
    return out


# ---------------------------------------------------------------- 谄媚
FLATTERY = [
    ("夸问题", r"这(?:是)?(?:个|一个)?[^，。！\n]{0,6}好(?:的)?问题|提得好|问得好|这问题问得"),
    ("夸提问者",
     r"(?:能)?看得出?你|你(?:的)?[^，。\n]{0,8}(?:清晰|敏锐|很到位|很深刻)|这本身(?:就)?很难得|"
     r"已经是(?:很)?好的开始(?:了)?|你(?:已经)?想得很(?:清楚|明白)|看得出[^，。]{0,6}(?:认真|用心)"),
    ("无据肯定",
     r"你的?(?:方向|想法|做法|选择|判断)是(?:对|正确)的|这个(?:想法|思路|方向)很有(?:价值|意义|前途)|"
     r"完全同意你|你说得很对|你的担心一点(?:都)?不(?:过分|多余)"),
    ("讨好收尾",
     r"随时(?:可以)?(?:找我|问我|联系我|和我说)|我很乐意|(?:愿意)?帮你(?:一起)?(?:分析|看看|梳理)|"
     r"祝(?:你|您)(?:一切顺利|生活愉快|学习愉快|工作顺利)|希望[^，。\n]{0,10}(?:对你|对您)?(?:有所)?帮助|"
     r"期待(?:你的)?(?:反馈|回复|回信)|欢迎(?:随时)?交流"),
]

# ---------------------------------------------------------------- 假中立
# 判据：对冲 **且** 没有内容。光有「各有优缺点」「因人而异」不算。
# 只要同一句里给了结论或具体条件，就不判 —— 见 _is_grounded()
CONCESSION = re.compile(r"但|但是|然而|不过|反而|而是|却是|我判断|我认为|我的判断|结论|"
                        r"利大于弊|弊大于利|更适合|不适合|成立|行不通|我倾向")

FALSE_NEUTRAL = [
    ("无结论",
     r"没有标准答案|没有绝对的对错|不能一概而论|难以下定论|不能简单(?:认定|判断|说)|"
     r"是优是劣|尚未形成共识|结论可能截然不同|不存在(?:放之四海而皆准|普适)|难以(?:简单)?评判"),
    ("两边对举",
     r"一方面[\s\S]{0,80}?另一方面|从[^，。]{2,6}角度看[\s\S]{0,90}?从[^，。]{2,6}角度(?:看|来说)|"
     r"在[^，。]{2,8}层面[\s\S]{0,80}?在[^，。]{2,8}层面|利[：:][\s\S]{0,60}?弊[：:]|"
     r"其一[，、][\s\S]{0,120}?其二"),
    ("各打五十大板",
     r"既[^，。]{2,20}又[^，。]{2,20}[，。]|优势[^。]{0,20}不足[^。]{0,20}(?:并存|同存)|"
     r"机遇与挑战并存|需要辩证(?:地)?(?:看待|分析)|有利有弊|双刃剑|一体两面|"
     r"辩证(?:地)?分析|寻找[^。]{0,10}平衡点|综合权衡|权衡各方面|伴随相应代价"),
    ("条件免责",
     r"在特定条件下?(?:可能)?|具体(?:情况)?(?:取决|视)[^。]{0,20}|视具体情况而定|因人而异|"
     r"取决于多方面因素|(?:效果|结论|最终)[^。]{0,6}取决于|结合自身(?:实际|情况)|"
     r"不同[^。，]{0,8}结论可能"),
]

# ---------------------------------------------------------------- 零风险
ZERO_RISK = [
    ("时代帽子", r"随着[^，。]{2,20}的(?:快速)?(?:发展|进步|普及|推进|深入|兴起|到来)|在当今|在这个[^，。]{0,12}的时代|随着时代的发展"),
    ("意义拔高", r"标志着?[^。]{0,20}(?:新篇章|新阶段|里程碑|分水岭|新时代)|具有(?:深远|重要|划时代)的?(?:意义|历史地位)|树立了?[^。]{0,10}标杆|彰显了?[^。]{0,16}(?:追求|决心|实力)"),
    ("虚假范围", r"从[^，。\d%]{2,14}到[^，。\d%]{2,14}[，。]"),
    ("空洞收尾", r"综上所述|总而言之|总的来说|让我们拭目以待|未来可期|充满无限可能|前景广阔|大有可为|不是终点[，,]?而是(?:一个)?新的?起点"),
    ("模糊归因", r"专家(?:指出|表示|认为)|业内人士(?:认为|表示)|有?研究表明|据了解|相关人士透露|权威数据显示|业界普遍认为|不少人认为"),
    ("元话语", r"本文将从[^。]{0,20}(?:方面|角度|维度)|接下来我们(?:来看|讨论|看看)|下面我们将|正如前面(?:提到|所述)|回到正题"),
]

# ---------------------------------------------------------------- 留白动作
UNCERTAINTY_MOVES = [
    ("①声明边界", r"只(?:在|对|适用于)[^。]{2,24}(?:时|情况下|成立|有效)|离开这个条件|换个[^，。]{2,16}就(?:不|完全没用)|换个做[^，。]{2,16}的"),
    ("②拒绝泛化", r"我给不出(?:一个)?(?:可复制的)?(?:方案)?(?:来)?|不太能推广|不敢说[^。]{0,16}也成立|"
                  r"没有普适(?:方案|性)|这一条完全没用|给不出(?:可复制|通用)的?(?:方案|答案)"),
    ("③降格为偏见", r"这算(?:是)?我(?:的)?一点?偏见|这只是我(?:的)?(?:看法|偏见|经验)|我的判断[^。]{0,10}(?:可能|或许)"),
    ("④削弱归因", r"也可能?只是运气|也可能是运气|不知道为什么(?:管用|有效|成)|没法回答|我没(?:法|有)(?:回答|普适)"),
]

# ---------------------------------------------------------------- 粗排
STRUCT = {
    "标题数": r"^#{1,6}\s+\S",
    "列表项": r"^\s*(?:[-*+]|\d+[.)])\s+\S",
}


def _sentence_at(text: str, pos: int, window: int = 80) -> str:
    """取命中所在的句子（以中文句末标点为界）。"""
    left = max(text.rfind(c, 0, pos) for c in "。！？\n") + 1
    ends = [i for i in (text.find(c, pos) for c in "。！？\n") if i != -1]
    right = min(ends) + 1 if ends else min(len(text), pos + window)
    return text[left:right]


def _is_grounded(text: str, pos: int) -> bool:
    """这一处对冲有没有内容托底。

    有内容 = 同一句里出现下面任一条：
      1. 结论或倾向（但/然而/我判断/利大于弊…）
      2. 冒号后跟具体条件（「因人而异：客户跨时区的适合」）

    注意：**句中有数字不算托底**。试过这条，结果是
    「从员工角度看省下两小时通勤」这种对举因为有数字而被放过，
    但它照样是空的对举。宁可这样严，也不放走对仗。
    """
    s = _sentence_at(text, pos)
    if CONCESSION.search(s):
        return True
    if re.search(r"[:：]\s*\S{4,}", s):
        return True
    return False


WEB_NOISE = [
    re.compile(r"https?://\S+"),                      # URL 本身
    re.compile(r"^\s*(?:来源|原标题|责任编辑|作者)[：:].*$", re.M),
    re.compile(r"^\s*\d{4}年\d{1,2}月\d{1,2}日\s*\d{1,2}:\d{2}\s*$", re.M),  # 发布时间
    re.compile(r"^\s*\d{4}/\d{1,2}/\d{1,2}\s*$", re.M),
    re.compile(r"^\s*中国作家网\s*·.*$", re.M),
    re.compile(r"^\s*本文节选自.*$", re.M),
]


def strip_web_noise(text: str) -> str:
    """去掉网页抓取残留。

    为什么必须做：中文网文抓下来，头部常带
        `来源：https://.../2026/1023/c404019-40820372.html` + `2026年10月30日08:15`
    这些 URL 里的数字会被 count_facts() 当成事实。
    实测三篇现代纪实，不清洗比清洗高 12%—17%（6.73 vs 5.81）。
    """
    out = text
    for p in WEB_NOISE:
        out = p.sub("", out)
    return out


# ---------------------------------------------------------------- 问题清单
# 两轮确认的第一步：把问题列成编号清单，带定位 / 原句 / 原因 / 建议。
# 只列不改 —— 改由人来勾选（见 SKILL.md §七 两个铁规矩）。
ISSUE_ADVICE = {
    # 谄媚（S 级：直接删）
    "夸问题": "整句删",
    "夸提问者": "整句删",
    "无据肯定": "整句删；要保留就给依据",
    "讨好收尾": "整句删",
    # 假中立（A 级：改写）
    "无结论": "给出你的判断，再用动作③降格为偏见",
    "两边对举": "删掉「从X角度看」，写你自己的角度",
    "各打五十大板": "「但」后面必须接结论：利大于弊还是弊大于利",
    "条件免责": "写出取决于什么（动作①声明边界）",
    # 零风险（A 级：改写或删）
    "时代帽子": "删。第一句换成只有本文才有的事实",
    "意义拔高": "写出实际发生了什么，删掉「标志/彰显/篇章」",
    "虚假范围": "删掉一头，或写出两者之间真实的因果",
    "空洞收尾": "删。结尾用具体动作或判断，不要祝愿",
    "模糊归因": "指名（谁/哪篇/哪年），或改成「我判断」",
    "元话语": "删。直接说事，别预告自己在写什么",
}
SEVERITY = {"谄媚": "S", "假中立": "A", "零风险": "A"}


def _para_index(text: str, pos: int) -> int:
    """命中的是第几段（空行分段，从 1 数）。"""
    head = text[:pos]
    paras = re.split(r"\n\s*\n", head)
    return max(1, len(paras))


def collect_issues(text: str, genre: str) -> list[dict]:
    """产出编号清单。每条：类型 / 级别 / 段号 / 原句 / 原因 / 建议。"""
    issues = []
    groups = [("谄媚", FLATTERY, False),
              ("假中立", FALSE_NEUTRAL, True),
              ("零风险", ZERO_RISK, False)]
    for gname, pats, grounded in groups:
        for cat, pat in pats:
            for m in re.finditer(pat, text):
                if grounded and _is_grounded(text, m.start()):
                    continue
                issues.append({
                    "级别": SEVERITY[gname],
                    "类型": f"{gname}·{cat}",
                    "段号": _para_index(text, m.start()),
                    "原文": m.group(0).strip(),
                    "上下文": _sentence_at(text, m.start())[:60],
                    "建议": ISSUE_ADVICE.get(cat, "按 references 对应条目改写"),
                })
    # 排序：先按段号（顺着读），同段内 S 级在前。
    # 注意不能直接按 "A"<"S" 排——那会把必须删的 S 级排到必须改的 A 级后面。
    sev_rank = {"S": 0, "A": 1}
    issues.sort(key=lambda x: (x["段号"], sev_rank.get(x["级别"], 9)))
    for i, it in enumerate(issues, 1):
        it["序号"] = i
    return issues


def render_issues(issues: list[dict], path: str) -> str:
    if not issues:
        return "未发现需要改的地方。"
    L = [f"在 {os.path.basename(path)} 里找到 {len(issues)} 处。**先确认，再动笔。**", ""]
    for it in issues:
        L.append(f"[{it['序号']:02d}] {it['级别']}级 · {it['类型']} · 第 {it['段号']} 段")
        L.append(f"     原句：{it['原文']}")
        L.append(f"     建议：{it['建议']}")
        L.append("")
    L.append(f"以上 {len(issues)} 处，哪些要改？回「全改」「都不改」或「改 1、3、5」。")
    L.append("在你回复之前，我不动笔，也不碰原文件。")
    return "\n".join(L)


def scan(text: str, genre: str) -> dict:
    text = strip_web_noise(text)
    cjk = len(re.findall(CJK, text))
    # 只处理中文。英文文本灌进来会得到"2 个中文字符、密度 300"这种无效数字，
    # 与其给假数，不如明确拒绝。
    # 判据：正文够长（≥200 非空白字符）但中文字符占比不足 30% → 不是中文稿。
    # 早先写成「中文字符 ≥50 才检查」，结果英文稿只有 2 个中文字符，条件直接漏过。
    nonspace = len(re.sub(r"\s", "", text))
    cjk_ratio = cjk / max(nonspace, 1)
    if nonspace >= 200 and cjk_ratio < 0.30:
        return {
            "错误": "非中文文本",
            "说明": f"中文字符仅占 {cjk_ratio*100:.0f}%，本工具只处理中文。"
                    f"英文计数口径未标定（两种合理定义差 2.8 倍），不提供英文结果。",
            "中文字符": cjk,
            "非空白字符": nonspace,
            "中文占比": round(cjk_ratio, 3),
        }
    facts = count_facts(text)
    per300 = round(len(facts) / max(cjk, 1) * 300, 2)

    def hits(pats, grounded_filter=False):
        out = []
        for name, pat in pats:
            ms = []
            for m in re.finditer(pat, text):
                if grounded_filter and _is_grounded(text, m.start()):
                    continue
                ms.append(m.group(0).strip())
            if ms:
                out.append({"类别": name, "次数": len(ms), "样例": ms[:3]})
        return out

    g = GENRES.get(genre, {"min": None, "n": 0, "p10": None, "note": ""})
    lo = g.get("min")
    if lo is None:
        verdict = "只报数（该类无足够人类样本，不设阈值）"
    elif per300 >= lo:
        verdict = "达标"
    else:
        verdict = "低于人类 P10"
    return {
        "字数": cjk,
        "事实数": len(facts),
        "每300字": per300,
        "文体": genre,
        "文体下限": lo,
        "人类样本n": g.get("n"),
        "人类P10": g.get("p10"),
        "置信度": g.get("conf"),
        "密度判定": verdict,
        "依据": g.get("note", ""),
        "事实样例": [v for _, v in facts[:12]],
        "谄媚": hits(FLATTERY),
        "假中立": hits(FALSE_NEUTRAL, grounded_filter=True),
        "零风险": hits(ZERO_RISK),
        "留白动作": hits(UNCERTAINTY_MOVES),
        "结构": {k: len(re.findall(v, text, re.M)) for k, v in STRUCT.items()},
        "清单": collect_issues(text, genre),
        "_note": "本工具只报计数，不判断文章好坏。可替换性测试与事实核实需人工完成。",
    }


def render(r: dict) -> str:
    if "错误" in r:
        return "\n".join([
            "=" * 66,
            "人类密度写作 · 验收",
            "=" * 66,
            f"[拒绝] {r['错误']}",
            f"  {r['说明']}",
            f"  实测：中文字符 {r['中文字符']}，非空白字符 {r['非空白字符']}，"
            f"中文占比 {r['中文占比']*100:.0f}%",
        ])
    L = []
    a = L.append
    a("=" * 66)
    a("人类密度写作 · 验收")
    a("=" * 66)
    a(f"中文字符 {r['字数']} ｜ 具体事实 {r['事实数']} ｜ 每 300 字 {r['每300字']}")
    n = r.get("人类样本n")
    conf = r.get("置信度")
    if r["文体下限"] is not None:
        a(f"文体「{r['文体']}」 下限 {r['文体下限']}（n={n}, 置信度={conf}）"
          f" → {r['密度判定']}")
    else:
        a(f"文体「{r['文体']}」 → {r['密度判定']}（{conf}）")
    if r.get("依据"):
        a(f"  依据：{r['依据']}")
    if r["事实样例"]:
        a(f"事实样例：{'、'.join(r['事实样例'])}")
    a("")

    bad = 0
    for key, label, sev in [("谄媚", "谄媚信号（S级，直接删）", "S"),
                            ("假中立", "假中立（A级，必须改写）", "A"),
                            ("零风险", "零风险/套话（A级）", "A")]:
        items = r[key]
        a(f"[{label}] 命中 {len(items)} 类")
        for it in items:
            bad += it["次数"]
            a(f"    ×{it['次数']}  {it['类别']}  ←  {' / '.join(it['样例'])}")
        if not items:
            a("    （无）")
        a("")

    a(f"[留白动作] 命中 {len(r['留白动作'])} 类")
    for it in r["留白动作"]:
        a(f"    {it['类别']}  ×{it['次数']}  ←  {' / '.join(it['样例'])}")
    if not r["留白动作"]:
        a("    （无。若文中存在「不知道」的地方，应使用四个动作之一，")
        a("      不要用「因人而异」「视情况而定」糊过去）")
    a("")

    a(f"[结构] 标题 {r['结构']['标题数']} ｜ 列表项 {r['结构']['列表项']}")
    a("")
    a("-" * 66)
    a("本工具查不了的（必须人做）：")
    a("  1. 可替换性测试 —— 把核心名词换掉，句子还成立吗")
    a("  2. 文中事实是否真的可查 —— 需要联网核实")
    a("  3. 结构是否为内容服务 —— 需要读完整篇")
    a("  4. 数字能否加总对上 —— 工具只列出数字，核对要人看")
    a("")
    a(f"合计需处理项：{bad}")
    return "\n".join(L)


def _sha(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(65536), b""):
            h.update(c)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description="人类密度写作验收器（只报计数，不打分）")
    ap.add_argument("path", nargs="?", help="稿件路径")
    ap.add_argument("--stdin", action="store_true")
    ap.add_argument("--genre", default="评论", choices=list(GENRES.keys()))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--issues", action="store_true",
                    help="只输出编号问题清单（两轮确认的第一轮），不写文件")
    ap.add_argument("--copy-to", metavar="PATH",
                    help="把待改稿复制一份到 PATH，之后只在副本上动笔；原件不动")
    args = ap.parse_args()

    if args.stdin:
        text = sys.stdin.read()
    elif args.path:
        p = args.path if os.path.isabs(args.path) else os.path.join(os.getcwd(), args.path)
        if not os.path.exists(p):
            print(f"找不到文件：{p}", file=sys.stderr)
            return 2
        text = open(p, encoding="utf-8").read()
    else:
        ap.print_help()
        return 1

    if not text.strip():
        print("输入为空。", file=sys.stderr)
        return 2

    r = scan(text, args.genre)

    # 副本优先：先把原件复制出去，之后一切改动都落在副本上。原件不动。
    if args.copy_to:
        if args.stdin:
            print("--copy-to 需要给出源文件路径（不能用 --stdin）", file=sys.stderr)
            return 2
        src = p
        dst = args.copy_to if os.path.isabs(args.copy_to) else os.path.join(os.getcwd(), args.copy_to)
        if os.path.exists(dst):
            print(f"副本已存在，不覆盖：{dst}", file=sys.stderr)
            return 2
        import shutil
        shutil.copy2(src, dst)
        same = _sha(src) == _sha(dst)
        print(f"已复制副本：{dst}")
        print(f"原件未动：{src}")
        print(f"两份 SHA256 {'一致 ✓' if same else '不一致 ← 复制有问题，停下'}")
        if not same:
            return 3

    if args.issues:
        print(render_issues(r.get("清单", []), p if args.path else "stdin"))
        return 0

    print(json.dumps(r, ensure_ascii=False, indent=2) if args.json else render(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())