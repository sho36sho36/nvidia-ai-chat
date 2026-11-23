import os, re, json, time, uuid, webbrowser, subprocess, tempfile, requests
from pathlib import Path
from datetime import datetime
from ddgs import DDGS
from textual import work, events
from textual.app import App
from textual.containers import VerticalScroll, Vertical, Horizontal
from textual.widgets import Header, Input, TextArea, Markdown, Collapsible, Static, Select, Button, ListView, ListItem, Label

SAVE_FILE = Path("nvidia_chats.json")
OUT_DIR = Path("ai_outputs")
OUT_DIR.mkdir(exist_ok=True)

MODELS = [
    ("Mistral Large 4", "mistralai/mistral-large-4-1t-a52b"),
    ("Nemotron 3.5 Bolt", "nvidia/nemotron-3.5-bolt-e4b"),
    ("Step 5 Preview", "stepfun-ai/step-5-preview"),
    ("GLM-5-3-Flash", "z-ai/glm-5-3-flash"),
    ("Muse Glimmer 30B", "meta/muse-glimmer-30b"),
]
EFFORTS = [("思考:Low", "low"), ("思考:Med", "medium"), ("思考:High", "high")]
SYS = (
    f"今日は{datetime.now():%Y年%m月%d日}。最新情報は推測せず `[SEARCH: 検索語]` のみ出力し、結果を受けて日本語で回答。"
    "ファイル作成を求められた時は可能な限り標準のMarkdownコードブロック(```python や ```html 等)で完全なコードを出力してください。"
)

SUP = str.maketrans("0123456789+-=()nijk", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱʲᵏ")
SUB = str.maketrans("0123456789+-=()aehijklmnoprstuvx", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ")
CAL = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "𝒜ℬ𝒞𝒟ℰℱ𝒢ℋℐ𝒥𝒦ℒℳ𝒩𝒪𝒫𝒬ℛ𝒮𝒯𝒰𝒱𝒲𝒳𝒴𝒵")
FRAK = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz", "𝔄𝔅ℭ𝔇𝔈𝔉𝔊ℌℑ𝔍𝔎𝔏𝔐𝔑𝔒𝔓𝔔ℜ𝔖𝔗𝔘𝔙𝔚𝔛𝔜ℨ𝔞𝔟𝔠𝔡𝔢𝔣𝔤𝔥𝔦𝔧𝔨𝔩𝔪𝔫𝔬𝔭𝔮𝔯𝔰𝔱𝔲𝔳𝔴𝔵𝔶𝔷")
BB = str.maketrans("CNQRZ", "ℂℕℚℝℤ")
EXT_MAP = {"python": ".py", "py": ".py", "html": ".html", "htm": ".html", "javascript": ".js", "js": ".js", "css": ".css", "json": ".json", "bat": ".bat", "cmd": ".bat", "ps1": ".ps1", "powershell": ".ps1", "sh": ".sh", "txt": ".txt", "md": ".md", "csv": ".csv", "sql": ".sql"}

MATH_TOKENS = [
    (r"\Longleftrightarrow", "⇔"), (r"\iff", "⇔"), (r"\implies", "⇒"), (r"\Rightarrow", "⇒"),
    (r"\Leftarrow", "⇐"), (r"\rightarrow", "→"), (r"\to", "→"), (r"\leftarrow", "←"), (r"\mapsto", "↦"),
    (r"\iiint", "∭"), (r"\iint", "∬"), (r"\oint", "∮"), (r"\int", "∫"),
    (r"\bigcup", "⋃"), (r"\bigcap", "⋂"), (r"\bigoplus", "⨁"), (r"\bigotimes", "⨂"),
    (r"\sum", "∑"), (r"\prod", "∏"), (r"\emptyset", "∅"), (r"\varnothing", "∅"),
    (r"\therefore", "∴"), (r"\because", "∵"), (r"\propto", "∝"), (r"\parallel", "∥"), (r"\perp", "⊥"),
    (r"\equiv", "≡"), (r"\approx", "≈"), (r"\neq", "≠"), (r"\leq", "≤"), (r"\geq", "≥"), (r"\sim", "∼"),
    (r"\land", "∧"), (r"\lor", "∨"), (r"\neg", "¬"), (r"\forall", "∀"), (r"\exists", "∃"),
    (r"\notin", "∉"), (r"\in", "∈"), (r"\subseteq", "⊆"), (r"\subset", "⊂"), (r"\supseteq", "⊇"), (r"\supset", "⊃"),
    (r"\cup", "∪"), (r"\cap", "∩"), (r"\times", "×"), (r"\div", "÷"), (r"\pm", "±"), (r"\mp", "∓"),
    (r"\infty", "∞"), (r"\partial", "∂"), (r"\nabla", "∇"), (r"\hbar", "ℏ"), (r"\lim", "lim"),
    (r"\langle", "⟨"), (r"\rangle", "⟩"), (r"\triangle", "△"), (r"\angle", "∠"), (r"\cdot", "·"),
    (r"\Alpha", "Α"), (r"\Beta", "Β"), (r"\Gamma", "Γ"), (r"\Delta", "Δ"), (r"\Theta", "Θ"),
    (r"\Lambda", "Λ"), (r"\Xi", "Ξ"), (r"\Pi", "Π"), (r"\Sigma", "Σ"), (r"\Phi", "Φ"), (r"\Psi", "Ψ"), (r"\Omega", "Ω"),
    (r"\alpha", "α"), (r"\beta", "β"), (r"\gamma", "γ"), (r"\delta", "δ"), (r"\epsilon", "ε"), (r"\varepsilon", "ε"),
    (r"\zeta", "ζ"), (r"\eta", "η"), (r"\theta", "θ"), (r"\iota", "ι"), (r"\kappa", "κ"), (r"\lambda", "λ"),
    (r"\mu", "μ"), (r"\nu", "ν"), (r"\xi", "ξ"), (r"\pi", "π"), (r"\rho", "ρ"), (r"\sigma", "σ"),
    (r"\tau", "τ"), (r"\upsilon", "υ"), (r"\phi", "φ"), (r"\varphi", "φ"), (r"\chi", "χ"), (r"\psi", "ψ"), (r"\omega", "ω"),
    (r"\quad", "  "), (r"\qquad", "    "), (r"\left", ""), (r"\right", ""),
]
def _conv_matrix(m):
    rows = [r.strip() for r in re.split(r"\\\\", m.group(2).strip()) if r.strip()]
    fmt = " / ".join("  ".join(c.strip() for c in r.split("&")) for r in rows)
    return f"[ {fmt} ]"

def _conv_root(m):
    deg, body = m.group(1).strip(), m.group(2)
    if deg == "3": return f"∛({body})"
    if deg == "4": return f"∜({body})"
    return f"{deg.translate(SUP)}√({body})"

def _conv_math(s: str) -> str:
    s = re.sub(r"\\begin\{((?:p|b|v|B|V)?matrix)\}(.*?)\\end\{\1\}", lambda m: "[ " + " / ".join("  ".join(x.strip() for x in r.split("&")) for r in re.split(r"\\\\", m.group(2).strip()) if r.strip()) + " ]", s, flags=re.S)
    for k, v in MATH_TOKENS:
        s = s.replace(k, v)
    s = re.sub(r"\\(?:mathcal|mathscr)\{([^{}]+)\}", lambda m: m.group(1).translate(CAL), s)
    s = re.sub(r"\\mathfrak\{([^{}]+)\}", lambda m: m.group(1).translate(FRAK), s)
    s = re.sub(r"\\mathbb\{([^{}]+)\}", lambda m: m.group(1).translate(BB), s)
    s = re.sub(r"\\vec\{([^{}]+)\}", r"\1⃗", s)
    s = re.sub(r"\\overline\{([^{}]+)\}", r"\1̅", s)
    s = re.sub(r"\\bar\{([^{}]+)\}", r"\1̄", s)
    s = re.sub(r"\\hat\{([^{}]+)\}", r"\1̂", s)
    s = re.sub(r"\\(?:mathbf|textbf|text|mathrm)\{([^{}]+)\}", r"\1", s)
    s = re.sub(r"\\binom\{([^{}]+)\}\{([^{}]+)\}", r"(\1 C \2)", s)
    s = re.sub(r"\\sqrt\[([^\]]+)\]\{([^{}]+)\}", _conv_root, s)
    s = re.sub(r"\\sqrt\{([^{}]+)\}", r"√(\1)", s)
    for _ in range(3):
        s = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"(\1/\2)", s)
    s = re.sub(r"\^\{([^{}]+)\}", lambda m: m.group(1).translate(SUP), s)
    s = re.sub(r"\^([0-9a-zA-Z+-])", lambda m: m.group(1).translate(SUP), s)
    s = re.sub(r"_\{([^{}]+)\}", lambda m: m.group(1).translate(SUB), s)
    s = re.sub(r"_([0-9a-zA-Z+-])", lambda m: m.group(1).translate(SUB), s)
    return s

def render_math(text: str) -> str:
    parts = re.split(r"(```.*?```)", text, flags=re.S)
    for i in range(0, len(parts), 2):
        seg = parts[i]
        seg = re.sub(r"\$\$(.+?)\$\$", lambda m: f"\n> **{_conv_math(m.group(1).strip())}**\n", seg, flags=re.S)
        seg = re.sub(r"\\\[(.+?)\\\]", lambda m: f"\n> **{_conv_math(m.group(1).strip())}**\n", seg, flags=re.S)
        seg = re.sub(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", lambda m: f"`{_conv_math(m.group(1).strip())}`", seg)
        seg = re.sub(r"\\\((.+?)\\\)", lambda m: f"`{_conv_math(m.group(1).strip())}`", seg)
        parts[i] = _conv_math(seg)
    return "".join(parts)

def extract_blocks(text: str):
    blocks = []
    for m in re.finditer(r"```([a-zA-Z0-9_+-]*)\s*\n(.*?)```", text, flags=re.S):
        lang = (m.group(1) or "txt").strip().lower()
        code = m.group(2)
        ext = EXT_MAP.get(lang, f".{lang}" if lang else ".txt")
        blocks.append((lang, ext, code))
    return blocks

def search(q: str) -> str:
    try:
        res = DDGS().text(q, region="jp-jp", max_results=3)
        return "\n".join(f"- [{r['title']}]({r['href']}): {r['body']}" for r in res) or "無"
    except Exception as e:
        return f"Err:{e}"
class MD(Markdown):
    ALLOW_SELECT = False

class ChatInput(TextArea):
    def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.prevent_default(); event.stop(); self.app.submit_chat()
        elif event.key == "shift+enter":
            event.prevent_default(); event.stop(); self.insert("\n")
        else:
            super()._on_key(event)

class Turn(Vertical):
    def __init__(self, t):
        super().__init__(); self.t = t
    def compose(self):
        yield Static(f"🧑 {self.t['q']} [dim]({self.t['m']})[/dim]", classes="u")
        with Collapsible(title=f"🔍 検索({'有' if self.t['s'] else '無'})", collapsed=True, id="sb"):
            yield MD(self.t['s'] or "*無*", id="sm")
        with Collapsible(title=f"🧠 思考({len(self.t['r'])}字)" if self.t['r'] else "🧠 思考", collapsed=True, id="tb"):
            yield MD(render_math(self.t['r']) if self.t['r'] else "*無*", id="tm")
        yield MD(render_math(self.t['a']), id="am")
        yield Horizontal(id="act-bar", classes="act-bar")
        with Collapsible(title="💻 実行結果 / 保存ログ", collapsed=True, id="eb", classes="hidden"):
            yield MD("*未実行*", id="em")
        yield Static(self.t['st'], classes="st", id="st")

    def on_mount(self):
        self.rebuild_actions()

    def rebuild_actions(self):
        bar = self.query_one("#act-bar", Horizontal)
        bar.remove_children()
        blocks = extract_blocks(self.t.get("a", ""))
        for idx, (lang, ext, code) in enumerate(blocks):
            tag = f"#{idx+1} " if len(blocks) > 1 else ""
            b_save = Button(f"💾 {tag}保存({ext})", classes="act-btn", variant="success")
            b_save.act_info = ("save", idx, lang, ext, code)
            bar.mount(b_save)
            if ext in (".py", ".html", ".js", ".bat", ".ps1"):
                label = "🌐 ブラウザ実行" if ext == ".html" else f"▶ {tag}実行({ext})"
                b_run = Button(label, classes="act-btn", variant="warning")
                b_run.act_info = ("run", idx, lang, ext, code)
                bar.mount(b_run)

class AppChat(App):
    CSS = """
    Screen{background:#0d1117} #main,#lv,#r,#sc{height:1fr}
    #side{width:25;background:#161b22;border-right:solid #30363d;padding:1}
    #btns{height:3;margin-bottom:1} #btns Button{min-width:5;margin-right:1}
    #q{margin-bottom:1} #lv{background:#0d1117}
    #bar{height:3;padding:0 1;background:#161b22} #ms{width:2fr;margin-right:1} #es{width:1fr}
    #sc{padding:1;overflow-y:scroll}
    Turn{margin-bottom:1;padding:1;border:round #30363d;background:#161b22;height:auto}
    .u{color:#58a6ff;text-style:bold;margin-bottom:1}
    Collapsible{margin-bottom:1;background:#0d1117;border:solid #30363d}
    MarkdownFence{overflow-x:auto}
    .act-bar{height:auto;margin-top:1}
    .act-btn{min-width:12;height:3;margin-right:1}
    .st{margin-top:1;color:#7ee787}
    #inp{dock:bottom;height:4;margin:0 1 1 1;border:tall #30363d}
    #ren{dock:bottom;height:3;margin:0 1 1 1;border:tall #f0883e;background:#161b22}
    .hidden{display:none}
    """
    def __init__(self):
        super().__init__()
        self.key, self.url = (os.getenv("NVIDIA_API_KEY") or "").strip(), (os.getenv("NVIDIA_INVOKE_URL") or "").strip()
        self.chats, self.cid, self.busy = {}, None, False

    def compose(self):
        yield Header()
        with Horizontal(id="main"):
            with Vertical(id="side"):
                with Horizontal(id="btns"):
                    yield Button("+新規", id="new", variant="success")
                    yield Button("名変", id="renb", variant="primary")
                    yield Button("削除", id="del", variant="error")
                yield Input(placeholder="🔍 全文検索...", id="q")
                yield ListView(id="lv")
            with Vertical(id="r"):
                with Horizontal(id="bar"):
                    yield Select(MODELS, value="mistralai/mistral-large-4-1t-a52b", id="ms", allow_blank=False)
                    yield Select(EFFORTS, value="low", id="es", allow_blank=False)
                yield VerticalScroll(id="sc")
                yield ChatInput(id="inp")
    def on_markdown_link_clicked(self, event: Markdown.LinkClicked) -> None:
        event.prevent_default(); event.stop()
        if event.href and event.href.startswith(("http://", "https://")):
            webbrowser.open(event.href)

    def save_data(self):
        try:
            SAVE_FILE.write_text(json.dumps({"cid": self.cid, "chats": self.chats}, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def load_data(self):
        if SAVE_FILE.exists():
            try:
                data = json.loads(SAVE_FILE.read_text(encoding="utf-8"))
                if data.get("chats"):
                    self.chats = data["chats"]
                    cid = data.get("cid")
                    self.go(cid if cid in self.chats else next(iter(self.chats)))
                    return
            except Exception:
                pass
        self.add_chat("チャット1")

    def on_mount(self):
        orig = self.screen._forward_event
        self.screen._forward_event = lambda e: self._safe(orig, e) if hasattr(e, "button") else orig(e)
        self.load_data()
        self.query_one("#inp").focus()

    def _safe(self, f, e):
        try: f(e)
        except AttributeError: pass

    def add_chat(self, t):
        c = uuid.uuid4().hex[:5]
        self.chats[c] = {"title": t, "msgs": [{"role": "system", "content": SYS}], "turns": []}
        self.go(c)

    def ref_lv(self, kw=""):
        lv = self.query_one("#lv", ListView); lv.clear(); k = kw.lower().strip()
        for c, d in self.chats.items():
            hit = (not k) or (k in d["title"].lower()) or any(
                k in t["q"].lower() or k in t["a"].lower() or k in t["r"].lower() or k in t["s"].lower()
                for t in d["turns"]
            )
            if hit:
                it = ListItem(Label(f"{'▶' if c==self.cid else ' '}{d['title']}({len(d['turns'])})"))
                it.cid = c; lv.append(it)

    async def _draw(self):
        sc = self.query_one("#sc", VerticalScroll); await sc.remove_children()
        for t in self.chats[self.cid]["turns"]: await sc.mount(Turn(t))
        sc.scroll_end(animate=False)

    def go(self, c):
        if not self.busy and c in self.chats:
            self.cid = c; self.save_data()
            self.ref_lv(self.query_one("#q", Input).value); self.run_worker(self._draw())

    def on_list_view_selected(self, e):
        if hasattr(e.item, "cid"): self.go(e.item.cid)

    async def on_button_pressed(self, e):
        if hasattr(e.button, "act_info"):
            mode, idx, lang, ext, code = e.button.act_info
            turn = next((w for w in e.button.ancestors if isinstance(w, Turn)), None)
            if turn:
                eb, em = turn.query_one("#eb", Collapsible), turn.query_one("#em", MD)
                eb.remove_class("hidden"); eb.collapsed = False
                if mode == "save":
                    fname = OUT_DIR / f"output_{datetime.now():%Y%m%d_%H%M%S}_{idx+1}{ext}"
                    fname.write_text(code, encoding="utf-8")
                    eb.title = f"💾 保存完了: {fname}"
                    em.update(f"✅ ファイルを保存しました:\n`{fname.resolve()}`")
                elif mode == "run":
                    eb.title = f"💻 実行中 ({ext})..."
                    em.update("⏳ *コードを実行しています...*")
                    self.exec_code(turn, ext, code)
            return

        if self.busy: return
        b = e.button.id
        if b == "new":
            self.add_chat(f"チャット{len(self.chats)+1}")
        elif b == "del":
            del self.chats[self.cid]
            if self.chats: self.go(next(iter(self.chats)))
            else: self.add_chat("チャット1")
        elif b == "renb":
            if self.query("#ren"): await self.query_one("#ren").remove()
            ren = Input(value=self.chats[self.cid]["title"], placeholder="新しいチャット名を入力してEnter...", id="ren")
            await self.query_one("#r").mount(ren); ren.focus()
    @work(thread=True)
    def exec_code(self, turn: Turn, ext: str, code: str):
        eb, em = turn.query_one("#eb", Collapsible), turn.query_one("#em", MD)
        ui = self.call_from_thread
        try:
            if ext == ".html":
                tmp = OUT_DIR / f"preview_{datetime.now():%H%M%S}.html"
                tmp.write_text(code, encoding="utf-8")
                full_path = str(tmp.resolve())
                if hasattr(os, "startfile"): os.startfile(full_path)
                else: webbrowser.open(tmp.resolve().as_uri())
                ui(setattr, eb, "title", f"🌐 ブラウザで開きました ({tmp.name})")
                ui(em.update, f"ブラウザでプレビューを表示しました:\n`{full_path}`")
                return

            with tempfile.NamedTemporaryFile("w", suffix=ext, delete=False, encoding="utf-8") as f:
                f.write(code); tmp_path = f.name

            cmd_map = {".py": ["py", tmp_path], ".js": ["node", tmp_path], ".bat": ["cmd", "/c", tmp_path], ".ps1": ["powershell", "-ExecutionPolicy", "Bypass", "-File", tmp_path]}
            res = subprocess.run(cmd_map.get(ext, ["py", tmp_path]), capture_output=True, text=True, timeout=15, encoding="utf-8", errors="replace")
            os.unlink(tmp_path)

            out, err = res.stdout.strip(), res.stderr.strip()
            body = (f"**標準出力:**\n```text\n{out}\n```\n" if out else "") + (f"**エラー出力:**\n```text\n{err}\n```\n" if err else "")
            ui(setattr, eb, "title", f"💻 実行完了 (終了コード: {res.returncode})")
            ui(em.update, body or "*（出力なし / 正常終了）*")
        except Exception as ex:
            ui(setattr, eb, "title", "❌ 実行エラー")
            ui(em.update, f"実行中にエラーが発生しました:\n`{ex}`")

    def on_input_changed(self, e):
        if e.input.id == "q": self.ref_lv(e.value)

    async def on_input_submitted(self, e):
        if e.input.id == "ren":
            if n := e.value.strip(): self.chats[self.cid]["title"] = n; self.save_data()
            await e.input.remove(); self.ref_lv(self.query_one("#q", Input).value); self.query_one("#inp").focus()

    def _hscroll(self, dx: int):
        for w in self.screen.get_widgets_at(*self.mouse_position):
            if hasattr(w, "scroll_x") and w.max_scroll_x > 0:
                w.scroll_to(x=max(0, min(w.max_scroll_x, w.scroll_x + dx)), animate=False); return

    def _on_mouse_scroll_up(self, e: events.MouseScrollUp):
        if e.shift or e.ctrl: self._hscroll(-6)
        else: sc = self.query_one("#sc", VerticalScroll); sc.scroll_to(y=max(0, sc.scroll_y-5), animate=False)
        e.prevent_default(); e.stop()

    def _on_mouse_scroll_down(self, e: events.MouseScrollDown):
        if e.shift or e.ctrl: self._hscroll(6)
        else: sc = self.query_one("#sc", VerticalScroll); sc.scroll_to(y=min(sc.max_scroll_y, sc.scroll_y+5), animate=False)
        e.prevent_default(); e.stop()

    def _on_mouse_scroll_left(self, e: events.MouseScrollLeft): self._hscroll(-6); e.prevent_default(); e.stop()
    def _on_mouse_scroll_right(self, e: events.MouseScrollRight): self._hscroll(6); e.prevent_default(); e.stop()
    def _btm(self): sc = self.query_one("#sc", VerticalScroll); return (sc.max_scroll_y - sc.scroll_y) <= 1.0
    def _asc(self, ok):
        if ok: self.query_one("#sc", VerticalScroll).scroll_end(animate=False)

    def submit_chat(self):
        inp = self.query_one("#inp", ChatInput)
        if not (txt := inp.text.strip()) or self.busy: return
        inp.text = ""; inp.disabled = True; self.busy = True
        mid, eff = str(self.query_one("#ms", Select).value), str(self.query_one("#es", Select).value)
        chat = self.chats[self.cid]
        if not chat["turns"] and chat["title"].startswith("チャット"):
            chat["title"] = next(iter(txt.splitlines()), txt).strip()[:12]
        chat["msgs"].append({"role": "user", "content": txt})
        td = {"q": txt, "m": f"{mid.split('/')[-1]}|{eff}", "a": "⏳ *接続中...*", "r": "", "s": "", "st": ""}
        chat["turns"].append(td); self.save_data(); self.ref_lv(self.query_one("#q", Input).value)
        turn = Turn(td); sc = self.query_one("#sc", VerticalScroll)
        self.run_worker(self._mount_and_run(sc, turn, chat, td, mid, eff))

    async def _mount_and_run(self, sc, turn, chat, td, mid, eff):
        await sc.mount(turn); sc.scroll_end(animate=False); self.agent(turn, chat, td, mid, eff)

    @work(thread=True)
    def agent(self, turn, chat, td, mid, eff):
        sb, sm, tb, tm = turn.query_one("#sb"), turn.query_one("#sm"), turn.query_one("#tb"), turn.query_one("#tm")
        am, st, inp, ui = turn.query_one("#am"), turn.query_one("#st"), self.query_one("#inp"), self.call_from_thread
        hdr = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json", "Accept": "text/event-stream"}
        t0, ta, tn, pt, ct, tt, logs, rall = time.perf_counter(), 0.0, 0.0, 0, 0, 0, [], ""
        try:
            for _ in range(3):
                pay = {"model": mid, "messages": chat["msgs"], "max_tokens": 4096, "stream": True, "stream_options": {"include_usage": True}, "temperature": 0.5}
                if "nemotron" not in mid: pay["reasoning_effort"] = eff
                res = requests.post(self.url, headers=hdr, json=pay, stream=True, allow_redirects=False)
                if res.status_code != 200: td["a"] = f"❌ Err({res.status_code})"; return ui(am.update, td["a"])
                cnt, rsn, usg, lup = "", "", {}, 0.0
                for line in res.iter_lines():
                    if not line or not (s := line.decode()).startswith("data: "): continue
                    if (d := s[6:].strip()) == "[DONE]": break
                    try:
                        chk = json.loads(d); usg = chk.get("usage") or usg
                        dlt = next(iter(chk.get("choices") or []), {}).get("delta") or {}
                        if r := dlt.get("reasoning_content"): ta = ta or time.perf_counter()-t0; rsn += r
                        if c := dlt.get("content"): ta = ta or time.perf_counter()-t0; tn = tn or time.perf_counter()-t0; cnt += c
                        if time.perf_counter()-lup > 0.08:
                            lup = time.perf_counter(); b = self._btm()
                            if rsn: ui(setattr, tb, "title", f"🧠 思考({len(rall)+len(rsn)}字)"); ui(tm.update, render_math(rall+rsn))
                            ui(am.update, "🔍 *検索中...*" if cnt.strip().startswith("[SEARCH:") else (render_math(cnt) or "🧠 *思考中...*")); ui(self._asc, b)
                    except Exception: pass
                pt += usg.get("prompt_tokens", 0); ct += usg.get("completion_tokens", 0) or int((len(cnt)+len(rsn))*0.7); tt += usg.get("total_tokens", 0)
                if rsn: rall += f"{rsn}\n\n"
                if m := re.search(r"\[SEARCH:\s*(.+?)\]", cnt):
                    q = m.group(1).strip(); ui(am.update, f"🌐 **検索:** `{q}`")
                    ll = f"**🔎 {q}**\n{search(q)}"; logs.append(ll); td["s"] = "\n\n---\n\n".join(logs)
                    ui(sm.update, td["s"]); ui(setattr, sb, "title", f"🔍 検索({len(logs)}回)")
                    chat["msgs"] += [{"role": "assistant", "content": f"[SEARCH: {q}]"}, {"role": "user", "content": f"検索結果:\n{ll}"}]; continue
                b = self._btm(); td["r"], td["a"] = rall.strip(), cnt
                ui(setattr, tb, "title", f"🧠 思考({len(td['r'])}字)" if td["r"] else "🧠 思考無")
                if td["r"]: ui(tm.update, render_math(td["r"]))
                ui(am.update, render_math(cnt)); chat["msgs"].append({"role": "assistant", "content": cnt})
                ui(turn.rebuild_actions); ui(self._asc, b); break
            dt = time.perf_counter()-t0
            td["st"] = f"📊 入力:{pt}|出力:{ct}|計:{tt or pt+ct} ⏱ 思考:{max(tn-ta,0.0) if tn else 0.0:.1f}s|総:{dt:.2f}s|⚡ {ct/max(dt-ta,0.01):.1f}tok/s"
            ui(st.update, td["st"])
        except Exception as e: td["a"] = f"❌ {e}"; ui(am.update, td["a"])
        finally:
            self.save_data(); self.busy = False; ui(setattr, inp, "disabled", False); ui(inp.focus)

if __name__ == "__main__": AppChat().run()


