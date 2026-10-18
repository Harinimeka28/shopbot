"""Grounded shopping assistant. Stdlib only. Run: python server.py  ->  http://localhost:8000
Every price/stock/rating comes from a catalogue record via templates (the LLM never writes them)."""
import csv, json, math, re, os, time, uuid, sys
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CATALOGUE = os.environ.get("CATALOGUE", "catalogue.csv")   # .csv or .json
POLICY = os.environ.get("POLICY", "policy.txt")
COSTS = "costs.csv"
FIELDS = {"id": ["id", "product_id", "sku"], "title": ["title", "name"], "description": ["description", "desc"],
          "price": ["price", "mrp", "selling_price"], "stock": ["stock", "stock_status", "availability", "in_stock"],
          "category": ["category"], "rating": ["rating", "ratings", "avg_rating"], "attributes": ["attributes", "attrs"]}
STOP = set("the a an is are do you have i want me for of in on to and with show find get any what which kya hai hain "
           "mein me ka ki ke chahiye chahie please pls need sell u there can give looking look some good best "
           "under below above than less more over tak se kam price cost how much kitna kitne kimat rate mrp stock "
           "available rating review budget rs inr already said k dikhao dikha batao do dena wala wali liye din hi hello hey hii namaste thanks ok".split())
SYN = {"sasta": "cheap", "saste": "cheap", "kapde": "clothing", "kapda": "clothing", "juta": "shoe", "jute": "shoe",
       "joote": "shoe", "chappal": "sandal", "ghadi": "watch", "laal": "red", "lal": "red", "neela": "blue", "nila": "blue",
       "kala": "black", "kaala": "black", "safed": "white", "hara": "green", "peela": "yellow", "suti": "cotton",
       "sooti": "cotton", "tshirt": "t-shirt", "sneakers": "shoe", "sneaker": "shoe", "mobile": "phone", "bag": "bag"}
COLORS = set("red blue black white green yellow grey gray pink brown orange purple navy beige maroon".split())
MATERIALS = set("cotton leather denim wool silk linen polyester steel plastic wood rubber nylon".split())
POLICY_WORDS = set("return refund exchange shipping delivery deliver warranty replace replacement cancel cancellation policy guarantee".split())

def stem(t): return t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t
def tokenize(s):
    out = []
    for t in re.findall(r"[a-z0-9]+", s.lower()):
        t = stem(SYN.get(t, t)); out.append(SYN.get(t, t))
    return out
def money(p): return "₹{:,.0f}".format(p)

# ---------- data ----------
def load_catalogue():
    if CATALOGUE.endswith(".json"):
        raw = json.load(open(CATALOGUE, encoding="utf-8")); raw = raw.get("products", raw) if isinstance(raw, dict) else raw
    else:
        raw = list(csv.DictReader(open(CATALOGUE, encoding="utf-8-sig")))
    out = []
    for r in raw:
        r = {k.lower().strip(): v for k, v in r.items()}
        g = lambda f: next((r[k] for k in FIELDS[f] if k in r and r[k] not in (None, "")), "")
        attrs = g("attributes"); attrs = "; ".join(f"{k}: {v}" for k, v in attrs.items()) if isinstance(attrs, dict) else str(attrs)
        try: price = float(re.sub(r"[^\d.]", "", str(g("price"))))
        except ValueError: price = None
        st = str(g("stock")).lower()
        in_stock = not (re.search(r"out|unavail|^0$|false|no", st))
        p = dict(id=str(g("id")), title=str(g("title")), description=str(g("description")), price=price, in_stock=in_stock,
                 category=str(g("category")), rating=str(g("rating")), attrs=attrs)
        p["text"] = " ".join([p["title"], p["category"], p["description"], p["attrs"]]).lower()
        p["toks"] = tokenize(p["title"]) * 3 + tokenize(p["category"]) * 2 + tokenize(p["description"] + " " + p["attrs"])
        out.append(p)
    return out

def load_policy():
    if not os.path.exists(POLICY): return []
    txt = open(POLICY, encoding="utf-8").read()
    parts = re.split(r"\n(?=\s*(?:#+\s|\d+[\.\)]\s|[A-Z][A-Za-z &/]{2,40}:?\s*\n))", txt)
    secs = []
    for i, part in enumerate(p for p in parts if p.strip()):
        lines = part.strip().split("\n"); head = lines[0].strip("# :").strip(); body = " ".join(lines[1:]).strip() or head
        secs.append(dict(id=f"POLICY §{len(secs)+1}", title=head, body=body, toks=tokenize(head) * 2 + tokenize(body)))
    return secs

class BM25:
    def __init__(s, docs, k1=1.4, b=.75):
        s.N = len(docs); s.avg = sum(map(len, docs)) / max(1, s.N); s.tf = [Counter(d) for d in docs]; s.len = list(map(len, docs)); s.k1, s.b = k1, b
        df = Counter(t for d in docs for t in set(d)); s.idf = {t: math.log(1 + (s.N - n + .5) / (n + .5)) for t, n in df.items()}
    def score(s, q, i):
        tf = s.tf[i]; return sum(s.idf[t] * tf[t] * (s.k1 + 1) / (tf[t] + s.k1 * (1 - s.b + s.b * s.len[i] / s.avg)) for t in q if t in tf)

CAT = load_catalogue(); POL = load_policy()
CBM = BM25([p["toks"] for p in CAT]); PBM = BM25([s["toks"] for s in POL]) if POL else None
VOCAB = {t for p in CAT for t in p["toks"]}; BYID = {p["id"].lower(): p for p in CAT}
CATEGORIES = sorted({p["category"] for p in CAT if p["category"]})

# ---------- understanding ----------
def num(x, k): return float(x.replace(",", "")) * (1000 if k else 1)
def extract_slots(q):
    q = q.lower(); q = re.sub(r"(?:₹|rs\.?|inr)\s*", " ", q); s = {}
    N = r"(\d[\d,]*(?:\.\d+)?)\s*(k)?\b"
    m = re.search(r"(?:under|below|less than|within|upto|up to|max(?:imum)?|budget(?: of| is)?|<=?)\s*" + N, q) or \
        re.search(N + r"\s*(?:tak|se kam|ke andar|se neeche)", q)
    if m: s["max"] = num(*m.groups())
    m = re.search(r"(?:above|over|more than|at least|min(?:imum)?|>=?)\s*" + N, q) or re.search(N + r"\s*se (?:zyada|upar|jyada)", q)
    if m: s["min"] = num(*m.groups())
    toks = set(tokenize(q)); c = (toks & COLORS) - {"gray"}; mt = toks & MATERIALS
    if c: s["color"] = sorted(c)[0]
    if mt: s["material"] = sorted(mt)[0]
    return s

SESS = {}
def new_state(): return dict(max=None, min=None, color=None, material=None, topic=[])

def filt(ps, st):
    out = []
    for p, sc in ps:
        if p["price"] is None: continue
        if st["max"] is not None and p["price"] > st["max"]: continue
        if st["min"] is not None and p["price"] < st["min"]: continue
        if st["color"] and st["color"] not in p["text"]: continue
        if st["material"] and st["material"] not in p["text"]: continue
        out.append((p, sc))
    return out

def describe(st):
    b = []
    if st["max"] is not None: b.append(f"under {money(st['max'])}")
    if st["min"] is not None: b.append(f"above {money(st['min'])}")
    if st["color"]: b.append(st["color"])
    if st["material"]: b.append(st["material"])
    return ", ".join(b)

def line(p, extra=True):
    stock = "in stock" if p["in_stock"] else "out of stock"
    r = f", rated {p['rating']}" if p["rating"] and extra else ""
    return f"{p['title']} — {money(p['price'])}, {stock}{r} [{p['id']}]", [p["id"]]

# ---------- main ----------
def respond(sid, q):
    T = {}; t0 = time.perf_counter()
    def lap(k):
        nonlocal t0; n = time.perf_counter(); T[k] = round((n - t0) * 1000, 2); t0 = n
    st = SESS.setdefault(sid, new_state()); ql = q.lower()
    if re.search(r"\b(reset|clear|start over|new search)\b", ql): SESS[sid] = st = new_state()
    toks = tokenize(q); slots = extract_slots(q)
    content = [t for t in toks if t not in STOP and not t.isdigit() and t not in COLORS and t not in MATERIALS and t != "cheap"]
    lap("normalize")
    kind, lines, options = "answer", [], []
    ids = [BYID[t] for t in re.findall(r"[a-z0-9\-_]+", ql) if t in BYID]
    lookup = bool(re.search(r"price|cost|kitna|kimat|rate\b|how much|stock|available|rating|review|mrp", ql))
    lap("route")

    if set(toks) & POLICY_WORDS and not ids:
        kind = "policy"
        sc = sorted(((PBM.score([t for t in content if t not in POLICY_WORDS] + [t for t in toks if t in POLICY_WORDS], i), i) for i in range(len(POL))), reverse=True) if PBM else []
        qs = set(content) | (set(toks) & POLICY_WORDS)
        if not sc or sc[0][0] <= 0 or not (qs & set(POL[sc[0][1]]["toks"])):
            kind = "refuse"; lines = [("I don't have that in the policy document, so I can't answer it.", [])]
        else:
            sec = POL[sc[0][1]]; sents = re.split(r"(?<=[.!?])\s+", sec["body"])
            best = sorted(sents, key=lambda s: -len(qs & set(tokenize(s))))[:2]
            for s in sorted(best, key=sents.index): lines.append((f"{s.strip()} [{sec['id']}]", [sec["id"]]))
        lap("retrieve")
    else:
        if ids: chosen = [(ids[0], 1.0)]
        else:
            # update multi-turn state
            if content and st["topic"] and not (set(content) & set(st["topic"])): st = SESS[sid] = new_state()
            qtok = content or st["topic"]
            if re.fullmatch(r"\W*(hi+|hello|hey|namaste|thanks|ok)\W*", ql): qtok = []; slots = {}
            if not qtok and not any(slots.values()):
                kind = "clarify"; lines = [("What are you looking for? Tell me a product type, and optionally a budget, colour or material.", [])]
                options = CATEGORIES[:6]; qtok = None
            if qtok:
                if content: st["topic"] = content
                for k, v in slots.items(): st[k] = v
                unknown = [t for t in qtok if t not in VOCAB]; qtok = [t for t in qtok if t in VOCAB] or qtok
                lap("slots")
                ranked = sorted(((p, CBM.score(qtok, i)) for i, p in enumerate(CAT)), key=lambda x: -x[1])
                top = ranked[0][1] if ranked else 0
                cov = len([t for t in qtok if t in ranked[0][0]["toks"]]) / len(qtok) if ranked else 0
                lap("retrieve")
                if len(unknown) / len(qtok) > .5 or top <= 0 or cov < .5:
                    kind = "refuse"; lines = [(f"I don't have that in the catalogue (nothing matches “{' '.join(qtok)}”).", [])]
                    if CATEGORIES: options = CATEGORIES[:6]
                else:
                    rel = [(p, s) for p, s in ranked if s >= .4 * top][:50]
                    ok = filt(rel, st); chosen = ok
                    meta = describe(st)
                    if not ok:
                        kind = "refuse"; lines = [(f"I found matching products but none {meta}." if meta else "No matching products.", [])]
                        for p, _ in sorted(rel, key=lambda x: x[0]["price"] or 1e9)[:2]:
                            t, c = line(p); lines.append(("Closest without your filters: " + t, c))
                    elif lookup and len(ok) > 1 and not (len(ok) >= 2 and ok[0][1] >= 1.5 * ok[1][1]):
                        kind = "clarify"
                        lines = [("I found several different products that fit — which one do you mean?", [])]
                        for p, _ in ok[:5]: lines.append((f"{p['title']} [{p['id']}] — {p['attrs'][:70]}", [p["id"]]))
                    elif lookup:
                        t, c = line(ok[0][0]); lines = [(t, c)]
                    else:
                        if meta: lines.append((f"Filters applied: {meta}.", None))
                        if unknown: lines.append((f"I couldn't find “{' '.join(unknown)}” in the catalogue, so I ignored it.", None))
                        lines.append((f"Best matches from the catalogue:", None))
                        for i, (p, _) in enumerate(ok[:3], 1):
                            t, c = line(p); lines.append((f"{i}. {t}", c))
                        if len(ok) > 3: lines.append((f"{len(ok)-3} more match. Add a budget or colour to narrow it down.", None))
                    chosen = None
            else: chosen = None
        if ids and chosen:
            lap("slots"); lap("retrieve"); t, c = line(chosen[0][0] if isinstance(chosen[0][0], dict) else chosen[0][0]); lines = [(t, c)]
    lap("generate")
    # verifier: every ₹ figure must equal the price of a cited record; uncited factual lines dropped
    final, cites = [], []
    for text, c in lines:
        if c is not None and c:
            allowed = {money(BYID[i.lower()]["price"]) for i in c if i.lower() in BYID}
            if any(n not in allowed for n in re.findall(r"₹\d+(?:,\d+)*", text)):
                continue
        final.append(text); cites += (c or [])
    if not final: final = ["I don't have that information in the catalogue."]; kind = "refuse"
    lap("verify")
    rec = dict(ts=time.strftime("%H:%M:%S"), query=q, kind=kind, **{f"ms_{k}": v for k, v in T.items()},
               total_ms=round(sum(T.values()), 2), llm_tokens_in=0, llm_tokens_out=0)
    new = not os.path.exists(COSTS)
    with open(COSTS, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rec)); new and w.writeheader(); w.writerow(rec)
    return dict(kind=kind, text="\n".join(final), cites=sorted(set(cites)), options=options, timings=T, total_ms=rec["total_ms"],
                tokens=dict(llm_in=0, llm_out=0), state={k: v for k, v in st.items() if k != "topic" and v is not None})

class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode(); self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path in ("/", "/index.html"): self._send(200, open("index.html", "rb").read(), "text/html")
        elif self.path == "/costs": self._send(200, open(COSTS, "rb").read() if os.path.exists(COSTS) else b"", "text/csv")
        else: self._send(404, "{}")
    def do_POST(self):
        d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/chat": self._send(200, json.dumps(respond(d.get("session") or str(uuid.uuid4()), d.get("message", "")), ensure_ascii=False))
        elif self.path == "/reset": SESS.pop(d.get("session"), None); self._send(200, "{}")
    def log_message(self, *a): pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000)); print(f"{len(CAT)} products, {len(POL)} policy sections -> http://localhost:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
