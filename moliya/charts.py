"""
Diagramma geometriyasi — SVG yo'llarini (path) hisoblab beradi.

Tashqi kutubxonasiz: barcha grafiklar sof SVG. Ranglar CSS o'zgaruvchilari
orqali keladi, shuning uchun mavzu almashganda diagramma ham moslashadi.

Rang tanlovi (dataviz standarti bo'yicha tekshirilgan):
  • Ikki qatorli (kirim/chiqim) grafiklar — ko'k va to'q sariq juftlik:
    rang ko'rmaslik (deuteran/protan) sharoitida ham ajraladi (ΔE 25+).
    Qo'shimcha belgi: kirim — to'liq chiziq, chiqim — punktir.
  • Bitta o'lchov reytingi (xarajat statyalari) — bitta rangning
    ochiqdan-to'qqa shkalasi (magnitude uchun to'g'ri tanlov).
  • Yashil/qizil faqat raqam va belgilar uchun qoladi (holat rangi).
"""
import math


# ══════════════════════════════════════════════════════════════════
#  Yordamchilar
# ══════════════════════════════════════════════════════════════════
def nice_max(v):
    """O'qish oson bo'lgan yuqori chegara (120 mln, 1.5 mlrd ...)."""
    if v <= 0:
        return 1.0
    exp = math.floor(math.log10(v))
    f = v / (10 ** exp)
    for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if f <= m:
            return m * (10 ** exp)
    return 10 ** (exp + 1)


def short_sum(v):
    """1 234 567 890 → «1,2 mlrd», 45 300 000 → «45 mln»."""
    a = abs(v)
    if a >= 1e9:
        s = f"{v/1e9:.1f}".rstrip("0").rstrip(".")
        return f"{s} mlrd"
    if a >= 1e6:
        return f"{v/1e6:.0f} mln" if a >= 1e7 else f"{v/1e6:.1f} mln".replace(".0 ", " ")
    if a >= 1e3:
        return f"{v/1e3:.0f} ming"
    return f"{v:.0f}"


def grp(v):
    return f"{v:,.0f}".replace(",", " ")


def _mono_path(pts):
    """Monoton kubik interpolyatsiya — ma'lumotdan «oshib ketmaydigan» silliq egri."""
    n = len(pts)
    if n == 0:
        return ""
    if n == 1:
        return f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    dxs = [xs[i + 1] - xs[i] for i in range(n - 1)]
    ms = [((ys[i + 1] - ys[i]) / dxs[i]) if dxs[i] else 0.0 for i in range(n - 1)]
    ts = [ms[0]]
    for i in range(1, n - 1):
        ts.append(0.0 if ms[i - 1] * ms[i] <= 0 else (ms[i - 1] + ms[i]) / 2)
    ts.append(ms[-1])
    for i in range(n - 1):
        if ms[i] == 0:
            ts[i] = 0.0
            ts[i + 1] = 0.0
    d = f"M{xs[0]:.1f},{ys[0]:.1f}"
    for i in range(n - 1):
        dx = dxs[i]
        d += (f" C{xs[i]+dx/3:.1f},{ys[i]+ts[i]*dx/3:.1f}"
              f" {xs[i+1]-dx/3:.1f},{ys[i+1]-ts[i+1]*dx/3:.1f}"
              f" {xs[i+1]:.1f},{ys[i+1]:.1f}")
    return d


# ══════════════════════════════════════════════════════════════════
#  1. AREA/LINE — vaqt bo'yicha o'zgarish (kirim va chiqim)
# ══════════════════════════════════════════════════════════════════
def line_area(datasets, labels, w=680, h=230, pad=(14, 16, 30, 56)):
    """datasets: [{'key','name','values'}, ...] — bir xil o'lchov birligida.

    Qaytadi: o'qlar, setka, har qator uchun line/area yo'llari va nuqtalar.
    """
    pt, pr, pb, pl = pad
    iw, ih = w - pl - pr, h - pt - pb
    n = max(len(labels), 1)
    vmax = nice_max(max([max(d["values"]) if d["values"] else 0
                         for d in datasets] + [1]))
    step = iw / max(n - 1, 1)

    def X(i):
        return pl + i * step

    def Y(v):
        return pt + ih - (v / vmax) * ih

    ticks = []
    for k in range(4 + 1):
        val = vmax * k / 4
        ticks.append({"y": round(Y(val), 1), "label": short_sum(val)})

    out = []
    for d in datasets:
        pts = [(X(i), Y(v)) for i, v in enumerate(d["values"])]
        line = _mono_path(pts)
        area = ""
        if line and len(pts) > 1:
            area = (line + f" L{pts[-1][0]:.1f},{pt+ih:.1f}"
                           f" L{pts[0][0]:.1f},{pt+ih:.1f} Z")
        out.append({**d, "line": line, "area": area,
                    "pts": [{"x": round(x, 1), "y": round(y, 1),
                             "v": d["values"][i]} for i, (x, y) in enumerate(pts)]})

    cols = [{"x": round(X(i), 1), "label": labels[i],
             "hx": round(X(i) - step / 2, 1), "hw": round(step, 1)}
            for i in range(n)]
    return {"w": w, "h": h, "pt": pt, "pl": pl, "ih": ih, "iw": iw,
            "base": round(pt + ih, 1), "ticks": ticks, "cols": cols,
            "series": out, "vmax": vmax}


# ══════════════════════════════════════════════════════════════════
#  2. WATERFALL — pul yil davomida qanday harakatlandi
# ══════════════════════════════════════════════════════════════════
def waterfall(steps, w=680, h=250, pad=(18, 10, 46, 56)):
    """steps: [{'name','value','kind'}] — kind: start|plus|minus|end."""
    steps = [s for s in steps
             if s["kind"] in ("start", "end") or abs(s["value"]) > 0.5]
    pt, pr, pb, pl = pad
    iw, ih = w - pl - pr, h - pt - pb
    # kümülyativ chegaralar
    cum = 0.0
    seg = []
    lo = hi = 0.0
    for s in steps:
        if s["kind"] in ("start", "end"):
            top, bot = (s["value"], 0.0)
            cum = s["value"]
        elif s["kind"] == "plus":
            bot, top = cum, cum + s["value"]
            cum = top
        else:
            top, bot = cum, cum - abs(s["value"])
            cum = bot
        seg.append({**s, "top": max(top, bot), "bot": min(top, bot)})
        lo = min(lo, min(top, bot))
        hi = max(hi, max(top, bot))
    span = (hi - lo) or 1.0
    vmax = nice_max(span)
    barw = iw / (len(steps) * 1.6)
    gap = (iw - barw * len(steps)) / max(len(steps) - 1, 1)

    def Y(v):
        return pt + ih - ((v - lo) / vmax) * ih

    bars, conns = [], []
    prev_x2 = prev_y = None
    for i, s in enumerate(seg):
        x = pl + i * (barw + gap)
        y1, y2 = Y(s["top"]), Y(s["bot"])
        bars.append({"x": round(x, 1), "y": round(y1, 1),
                     "w": round(barw, 1), "h": round(max(y2 - y1, 2), 1),
                     "cx": round(x + barw / 2, 1),
                     "name": s["name"], "kind": s["kind"],
                     "value": s["value"],
                     "label": ("+" if s["kind"] == "plus" else
                               "−" if s["kind"] == "minus" else "") + short_sum(abs(s["value"])),
                     "ly": round(y1 - 8, 1)})
        conn_y = Y(s["bot"] if s["kind"] == "minus" else s["top"])
        if prev_x2 is not None:
            conns.append({"x1": prev_x2, "x2": round(x, 1), "y": prev_y})
        prev_x2 = round(x + barw, 1)
        prev_y = round(conn_y, 1)
    return {"w": w, "h": h, "pt": pt, "pl": pl, "ih": ih,
            "base": round(pt + ih, 1), "bars": bars, "conns": conns,
            "zero": round(Y(0), 1)}


# ══════════════════════════════════════════════════════════════════
#  3. RANK BARS — statyalar reytingi (bitta o'lchov → bitta rang shkalasi)
# ══════════════════════════════════════════════════════════════════
def rank_bars(items, top=7):
    """items: [{'cat','val'}] → foiz va shaffoflik darajasi bilan."""
    rows = sorted(items, key=lambda x: -x["val"])[:top]
    total = sum(i["val"] for i in items) or 1.0
    mx = rows[0]["val"] if rows else 1.0
    out = []
    for i, r in enumerate(rows):
        out.append({"cat": r["cat"], "val": r["val"],
                    "pct": r["val"] / total * 100,
                    "w": r["val"] / mx * 100,
                    "shade": max(1.0 - i * 0.115, 0.32)})
    return {"rows": out, "total": total}


# ══════════════════════════════════════════════════════════════════
#  4. SPARKLINE — jadval qatoridagi mini trend
# ══════════════════════════════════════════════════════════════════
def sparkline(values, w=76, h=22):
    vals = [v for v in values]
    if not vals or max(vals) == 0:
        return None
    mx = max(vals) or 1
    n = len(vals)
    step = w / max(n - 1, 1)
    pts = [(i * step, h - 2 - (v / mx) * (h - 4)) for i, v in enumerate(vals)]
    last = pts[-1]
    return {"w": w, "h": h, "d": _mono_path(pts),
            "lx": round(last[0], 1), "ly": round(last[1], 1)}


# ══════════════════════════════════════════════════════════════════
#  5. BEP — zararsizlik grafigi (foyda chizig'i nolni kesib o'tadi)
# ══════════════════════════════════════════════════════════════════
def bep_chart(capacity, contribution, fixed_alloc, bep, w=560, h=210,
              pad=(16, 20, 34, 62)):
    """O'quvchilar soniga qarab foyda chizig'i + zararsizlik nuqtasi."""
    pt, pr, pb, pl = pad
    iw, ih = w - pl - pr, h - pt - pb
    n = max(int(capacity), 1)
    profits = [contribution * s - fixed_alloc for s in range(0, n + 1)]
    lo, hi = min(profits + [0]), max(profits + [0])
    span = (hi - lo) or 1.0

    def X(s):
        return pl + (s / n) * iw

    def Y(v):
        return pt + ih - ((v - lo) / span) * ih

    pts = [(X(s), Y(profits[s])) for s in range(0, n + 1)]
    line = _mono_path(pts)
    zero = Y(0)
    area_pos = f"{line} L{pts[-1][0]:.1f},{zero:.1f} L{pts[0][0]:.1f},{zero:.1f} Z"
    marker = None
    if bep is not None and 0 < bep <= n:
        marker = {"x": round(X(bep), 1), "y": round(zero, 1),
                  "label": f"{bep:.0f} o'quvchi"}
    return {"w": w, "h": h, "pt": pt, "pl": pl, "ih": ih, "iw": iw,
            "base": round(pt + ih, 1), "line": line, "area": area_pos,
            "zero": round(zero, 1), "marker": marker,
            "x0": pl, "x1": pl + iw,
            "cap_label": f"{n} o'rin",
            "ymax_label": short_sum(hi), "ymin_label": short_sum(lo),
            "last": {"x": round(pts[-1][0], 1), "y": round(pts[-1][1], 1),
                     "v": profits[-1]}}
