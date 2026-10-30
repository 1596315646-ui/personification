#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check.py 的离线回归测试。

每条断言都对着 `sources/corpus-findings.md` 里实测过的地面真相，
不是"跑通就行"。改动 check.py 的正则或计数口径后跑一遍，防止悄悄失效。

跑法：python selftest.py
"""

from __future__ import annotations

import hashlib
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check as C  # noqa: E402

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail and not cond else ""))


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(65536), b""):
            h.update(c)
    return h.hexdigest()


PROTECT = [os.path.join(HERE, "check.py")]
before = {p: sha(p) for p in PROTECT}

# ============================================================ 一、事实计数口径
# 语料里踩过的两个坑，各一条断言

# 坑 1：只匹配 \d+ 会漏中文数字
t = "去年三月我们全员转远程，第一个月开掉了两个人。上午十点发消息，下午三点回。"
n = len(C.count_facts(t))
ok("中文数字计入事实（两人/十点/三点/三月）", n >= 4, f"实际 {n}: {C.count_facts(t)}")

# 坑 2：列表编号与虚词「一」不计
t2 = "一、第一点\n二、第二点\n1. 第三点\n2、第四点\n"
ok("列表编号不计入", len(C.count_facts(t2)) == 0, str(C.count_facts(t2)))

t3 = "一方面要看成本，另一方面要看一致性，这是一律的规定，唯一的问题。"
ok("虚词「一」不计入", len(C.count_facts(t3)) == 0, str(C.count_facts(t3)))

# 按值去重会误杀真实重复（S-26 的三件事）
t4 = "跟三件事有关系：这三条成立就行。那三条不成立就没用。"
ok("同一数字重复出现应分别计数", len(C.count_facts(t4)) >= 3, str(C.count_facts(t4)))

# ============================================================ 二、密度梯度
LOW = "随着信息技术的飞速发展，远程办公已成为重要模式。它不仅打破地域限制，还带来诸多便利。综上所述，企业应积极探索适合自身的路径。"
HIGH = ("我们公司 43 个人，做工业软件实施。2023 年 6 月开始全员远程。第一年客户等了 26 小时，"
        "新招的 7 个应届生半年走了 4 个，差旅费降了 38 万，云服务涨了 11 万。第二年差旅只降了 21 万。")
r_lo, r_hi = C.scan(LOW, "纪实"), C.scan(HIGH, "纪实")
ok("空话稿密度低于下限", r_lo["每300字"] < 6, f"{r_lo['每300字']}")
ok("实料稿密度达标", r_hi["每300字"] >= 6, f"{r_hi['每300字']}")
ok("实料稿密度是空话稿的 5 倍以上",
   r_hi["每300字"] > r_lo["每300字"] * 5, f"{r_lo['每300字']} vs {r_hi['每300字']}")

# ============================================================ 三、谄媚四类
FLAT = [
    ("夸问题", "这是个非常好的问题！"),
    ("夸提问者", "能看出你在认真思考工作方式的优化，这本身就很难得。"),
    ("无据肯定", "你的方向是对的，完全同意你。"),
    ("讨好收尾", "随时可以问我，祝你一切顺利～"),
]
for name, s in FLAT:
    hits = [x for cat in C.FLATTERY for x in __import__("re").finditer(cat[1], s)]
    ok(f"谄媚能命中：{name}", len(hits) > 0, s)

# 不该误伤
CLEAN = "我不太赞成这个说法。它把一个管理问题偷换成了地点问题。效率跟人在哪儿没关系。"
ok("正常判断不触发谄媚", len(C.scan(CLEAN, "评论")["谄媚"]) == 0,
   str(C.scan(CLEAN, "评论")["谄媚"]))

# ============================================================ 四、假中立四种变体
NEUTRAL = [
    ("无结论", "这个问题没有标准答案，不能简单认定是优是劣。"),
    ("两边对举", "在效率层面，减少了通勤；在成本层面，压缩了支出。"),
    ("各打五十大板", "远程办公是一把双刃剑，需要辩证地分析。"),
    ("条件免责", "效果取决于组织能否建立结果导向的评价体系。"),
]
for name, s in NEUTRAL:
    r = C.scan(s, "评论")
    ok(f"假中立能命中：{name}", len(r["假中立"]) > 0, str(r["假中立"]))

# ============================================================ 五、假中立的边界
# 用户 2026-10-29 指出：「各有优缺点」「因人而异」是要写的。
# 对：判据不是这串字，是它后面有没有内容。这组断言守这条边界。

EDGE = [
    # (说明, 文本, 是否应判为假中立)
    ("空泛的各有优缺点+因人而异 应判", "远程办公各有优缺点，因人而异，取决于多方面因素。", True),
    ("有具体内容 不判", "客户跨时区的省下六小时时差，我们三个人改下午四点上班；做本地生意的多付沟通成本，去年试了四个月，报价回得慢一倍。", False),
    ("因人而异+冒号给出条件 不判", "能不能远程因人而异：客户跨时区的适合，做本地生意的就不适合。", False),
    ("双刃剑+但字给出结论 不判", "远程办公是一把双刃剑，但对我们这种 24 人的外贸公司，利大于弊。", False),
    ("纯辩证无结论 应判", "远程办公有优点也有缺点，需要辩证地看待，企业应结合自身实际综合权衡。", True),
    ("从X角度看对举（无结论）应判", "从员工角度看，远程省下每天两小时通勤。从企业角度看，办公成本下降。", True),
]
for name, txt, should in EDGE:
    got = len(C.scan(txt, "评论")["假中立"]) > 0
    ok(name, got == should, f"期望{'判' if should else '不判'}，实际{'判' if got else '不判'}")

# ============================================================ 六、留白四动作
MOVES = [
    ("①声明边界", "这个安排只在一种情况下成立：你的客户也不在你所在时区。"),
    ("②拒绝泛化", "如果你要一个可复制的方案，我给不出来。"),
    ("③降格为偏见", "6 个人以上，我没做成功过。这算是我的一点偏见。"),
    ("④削弱归因", "这七个字用了三年，没出过大问题，也可能只是运气好。"),
]
for name, s in MOVES:
    r = C.scan(s, "评论")
    ok(f"留白能识别：{name}", len(r["留白动作"]) > 0, str(r["留白动作"]))

# 假留白不该被当成真留白
FAKE = "当然，任何事物都有两面性，具体情况需要具体分析，因人而异。"
ok("假留白不被识别为真留白",
   len(C.scan(FAKE, "评论")["留白动作"]) == 0, str(C.scan(FAKE, "评论")["留白动作"]))

# ============================================================ 七、文体阈值
# 2026-10-29 两轮标定。第一轮据 AI-vs-AI 插值设了「纪实=6」，错。
# 第二轮据人类 P10 设了 技术/学术/演讲/短篇 四条，结果发现英文口径不稳（差 2.8 倍），
# 那三条又撤回。现在只剩中文短篇一条。下面守的就是这个"少"。

for g in ("短篇", "散文"):
    ok(f"「{g}」标定阈值（n=294, P10=1.55）",
       C.GENRES[g]["min"] == 1.5 and C.GENRES[g]["n"] == 294
       and C.GENRES[g]["conf"] == "标定", str(C.GENRES[g]))

ok("「纪实」有观察阈值（n=3, min=2.72）",
   C.GENRES["纪实"]["min"] == 2.7 and C.GENRES["纪实"]["conf"] == "观察",
   str(C.GENRES["纪实"]))

for g in ("纪实·文言", "书信", "科普", "文学评论", "评论", "公文", "学术", "技术", "演讲"):
    ok(f"「{g}」拒绝给阈值（口径不可测或样本不足）",
       C.GENRES[g]["min"] is None, str(C.GENRES[g]))

ok("只有 3 个体裁有阈值——多一个都要有依据才加",
   sum(1 for v in C.GENRES.values() if v["min"] is not None) == 3,
   str({k: v["min"] for k, v in C.GENRES.items() if v["min"] is not None}))

ok("标定级阈值必须 n≥100",
   all(v["n"] >= 100 for v in C.GENRES.values() if v.get("conf") == "标定"))
ok("文言类必须标为不可测（量词口径未覆盖）",
   all(C.GENRES[g]["conf"] == "不可测"
       for g in ("纪实·文言", "科普", "文学评论")))

# 网页头必须剥掉，否则 URL 里的数字被当成事实
NOISY = ("那些痛，那些爱\n中国作家网 · 当代｜《纪实专栏》\n"
         "来源：https://www.chinawriter.com.cn/n1/2026/1023/c404019-40820372.html\n\n"
         "来源：文艺报　|　韩青辰\n2026年10月30日08:15\n"
         "今夏，中国首批缉毒警察退休。看到微信推送时，我再次想起了三十年前看过的专题片。")
CLEAN = "今夏，中国首批缉毒警察退休。看到微信推送时，我再次想起了三十年前看过的专题片。"
n_noisy = C.scan(NOISY, "纪实")["事实数"]
n_clean = C.scan(CLEAN, "纪实")["事实数"]
ok("网页头（URL/发布时间）不计入事实", n_noisy == n_clean,
   f"带噪声 {n_noisy} vs 干净 {n_clean}")

# 空话稿在短篇档下应该低于 P10
r_bad = C.scan("随着时代发展，远程办公日益重要。它打破地域限制，带来诸多便利。综上所述前景广阔。", "短篇")
ok("空话稿低于人类 P10（1.5）", r_bad["密度判定"] != "达标", f"{r_bad['每300字']}")

# 正常叙事应该过线
r_mid = C.scan("1958 年我父亲从济南调到北京，一家五口挤在两间平房里。那年他 34 岁，工资 62 块。", "短篇")
ok("正常叙事密度达标", r_mid["密度判定"] == "达标", f"{r_mid['每300字']}")

# 无阈值体裁必须明确说"只报数"，不能悄悄判成不达标
r_doc = C.scan("本文描述协议的分层结构。", "技术")
ok("无阈值体裁报「只报数」而不是判不达标",
   "只报数" in r_doc["密度判定"], r_doc["密度判定"])

# ============================================================ 八、非中文输入必须拒绝
# 英文文本灌进来会得到「2 个中文字符、密度 300」这种假数。宁可拒绝。
EN_TEXT = ("Most people who bother with the matter at all would admit that the English "
           "language is in a bad way, but it is generally assumed that we cannot by "
           "conscious action do anything about it. Our civilization is decadent, and our "
           "language, so the argument runs, must inevitably share in the general collapse. "
           "It follows that any struggle against the abuse of language is a sentimental "
           "archaism, like preferring candles to electric light or hansom cabs to "
           "aeroplanes. Underneath this lies the half-conscious belief that language is a "
           "natural growth and not an instrument which we shape for our own purposes.")
r_en = C.scan(EN_TEXT, "评论")
ok("纯英文被拒绝，不给假密度", "错误" in r_en, str(r_en)[:120])
ok("拒绝时说明中文占比", "中文占比" in r_en, str(r_en)[:120])
ok("拒绝信息里说明了英文口径未标定",
   "未标定" in r_en.get("说明", "") or "2.8" in r_en.get("说明", ""), r_en.get("说明", ""))

# 中英混排但以中文为主，应正常处理
MIX = ("我们 2023 年 6 月开始全员远程，43 个人。客户等了 26 小时，差旅降了 38 万，"
       "云服务涨了 11 万。这些数字互相咬合，因为它们是真实的。" * 3)
ok("中英混排以中文为主时正常处理", "错误" not in C.scan(MIX, "短篇"), "被误拒")

# ============================================================ 九、两轮确认的编号清单
# SKILL.md §七 的铁规矩：先列清单、等确认、只改副本。
# 这一节守的是「清单真的能列，且格式齐全」。

DRAFT = ("这是个非常好的问题！下面我来谈谈远程办公。\n\n"
         "远程办公有优点也有缺点，需要辩证地看待。具体取决于实际情况。\n\n"
         "综上所述，企业应结合自身实际，综合权衡各方面因素。"
         "希望以上信息对您有所帮助，随时可以问我。")
iss = C.collect_issues(DRAFT, "评论")
ok("能列出编号清单", len(iss) >= 6, f"只列出 {len(iss)} 条")
ok("清单编号连续从 1 开始",
   [x["序号"] for x in iss] == list(range(1, len(iss) + 1)), str([x["序号"] for x in iss]))
ok("每条都有定位段号", all(x["段号"] >= 1 for x in iss))
ok("每条都有原句", all(x["原文"] for x in iss))
ok("每条都有建议", all(x["建议"] for x in iss))
ok("每条都有级别（S/A）", all(x["级别"] in ("S", "A") for x in iss), str([x["级别"] for x in iss]))

# 谄媚必须排在最前（S 级优先）
first_types = [x["级别"] for x in iss if x["段号"] == 1]
ok("谄媚在第一段被标为 S 级", "S" in first_types, str(first_types))

# S 级必须排在 A 级之前（不能按字母序把 A 排前面）
seg1 = [x["级别"] for x in iss if x["段号"] == 1]
if "S" in seg1 and "A" in seg1:
    ok("同段内 S 级排在 A 级之前",
       seg1.index("S") < seg1.index("A"), str(seg1))
else:
    ok("同段内 S 级排在 A 级之前（本段只有一种级别，跳过）", True)

# 段号要准
ok("第 2 段的问题被标成第 2 段",
   any(x["段号"] == 2 for x in iss), str([(x["段号"], x["类型"]) for x in iss]))

# 渲染出来的清单必须带「等确认」的收尾
rendered = C.render_issues(iss, "测试稿.md")
ok("清单末尾要求确认", "哪些要改" in rendered, rendered[-120:])
ok("清单声明不动原文件", "不碰原文件" in rendered or "不动笔" in rendered)
ok("无问题时给出干净结论", C.render_issues([], "x.md") == "未发现需要改的地方。")

# 空稿不能崩
ok("空稿的清单为空", C.collect_issues("", "评论") == [])

# ============================================================ 十、边界输入
for label, txt in [("空串", ""), ("纯标点", "。。。！"), ("纯数字", "123 456"),
                   ("纯英文", "Hello world, this is a test."), ("极短", "好。")]:
    try:
        r = C.scan(txt, "评论")
        good = isinstance(r["每300字"], float)
    except Exception as e:  # noqa: BLE001
        good, label = False, f"{label}(异常 {e})"
    ok(f"边界不崩：{label}", good)

# ============================================================ 八、输出字段完整
r = C.scan(HIGH, "纪实")
need = ["字数", "事实数", "每300字", "文体", "密度判定", "谄媚", "假中立", "零风险", "留白动作", "结构"]
ok("输出字段齐全", all(k in r for k in need), f"缺 {[k for k in need if k not in r]}")

# ============================================================ 九、生产文件未被改动
after = {p: sha(p) for p in before}
ok("check.py 未被测试改动", all(before[p] == after[p] for p in before))

# ============================================================
print()
print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    for f in FAIL:
        print("  失败：", f)
    raise SystemExit(1)
print("全部通过。")