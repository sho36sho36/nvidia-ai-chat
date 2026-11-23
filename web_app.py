from pypdf import PdfReader
import os, re, json, html, base64, io, time, uuid, hashlib, secrets, subprocess, tempfile, urllib.parse, xml.etree.ElementTree as ET, requests
from pathlib import Path
from datetime import datetime
from ddgs import DDGS
from fastapi import FastAPI, HTTPException, Header, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse, Response, Response
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel

app = FastAPI()
app.add_middleware(GZipMiddleware, minimum_size=500)
DATA_FILE = Path("web_data.json")
DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()
ADMIN_USER, ADMIN_PASS = "sho36", "shoma0121"
SESSIONS = {}

def _pg_conn():
    import psycopg2
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url)

def _init_pg():
    if not DATABASE_URL:
        return
    try:
        with _pg_conn() as conn, conn.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS app_kv (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
            conn.commit()
    except Exception as e:
        print("PG Init Error:", e)

_init_pg()

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "ユーザーの職業・学年・使用言語・好み・継続的な前提条件など、別の新しいチャットでも覚えておくべき重要な情報を長期記憶に保存する。",
            "parameters": {
                "type": "object",
                "properties": {"fact": {"type": "string", "description": "記憶する簡潔な事実（例: ユーザーはPythonとFastAPIでWebアプリを開発している）"}},
                "required": ["fact"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_memory",
            "description": "古くなった・誤っている・ユーザーが忘れるよう指示した長期記憶を削除する。",
            "parameters": {
                "type": "object",
                "properties": {"keyword": {"type": "string", "description": "削除対象の記憶に含まれるキーワード"}},
                "required": ["keyword"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_market_data",
            "description": "株価（日本株は7203.Tのように.T付き、米国株はNVDAやAAPL、指数は^N225）、為替レート（USDJPY=X）、暗号資産（BTC-USD, ETH-USD）の最新リアルタイム価格と変動率を取得する。",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "ティッカーシンボル（例: NVDA, 7203.T, ^N225, USDJPY=X, BTC-USD）"}
                },
                "required": ["symbol"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_wikipedia",
            "description": "人物、歴史、用語、科学技術、作品などの正確な定義や概要をWikipedia公式APIから検索して取得する。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "検索したい単語や人物名・用語"},
                    "lang": {"type": "string", "description": "言語コード（通常は ja、英語記事なら en）"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_arxiv",
            "description": "AI、機械学習、数学、物理学、コンピュータサイエンスなどの最新学術論文をarXiv公式APIで検索し、タイトル・著者・要旨・PDFリンクを取得する。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "英語の論文検索キーワード（例: Transformer, LLM reasoning, quantum error correction）"}},
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": "複雑な数学計算、統計処理、日付・曜日計算、シミュレーション、アルゴリズムの検証のためにPythonコードを実行し、標準出力を取得する。必ずprint()で結果を出力すること。",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string", "description": "実行するPythonコード（結果をprintで出力すること）"}},
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_url",
            "description": "指定されたURL（https://...）のWebページにアクセスし、記事やドキュメントの本文テキストを取得して読む。ユーザーがURLを提示した時や検索結果の詳細を読む時に使う。",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "読み込むWebページのURL"}},
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "指定された都市・地域の現在の天気予報、最高気温、最低気温、降水確率（3日分）をリアルタイム取得する。",
            "parameters": {
                "type": "object",
                "properties": {"location": {"type": "string", "description": "都市名（例: Yokohama, Tokyo, Osaka, 札幌）"}},
                "required": ["location"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "最新ニュース、時事、人物、価格、専門知識などをインターネットで検索する。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "検索キーワード"}},
                "required": ["query"]
            }
        }
    }
]

WMO = {0:"快晴",1:"晴れ",2:"一部曇り",3:"曇り",45:"霧",51:"弱い霧雨",53:"霧雨",61:"弱い雨",63:"雨",65:"強い雨",71:"弱い雪",73:"雪",75:"強い雪",80:"にわか雨",95:"雷雨"}

def get_market_data(symbol: str) -> str:
    sym = symbol.strip().upper()
    alias = {"USD/JPY": "USDJPY=X", "USDJPY": "USDJPY=X", "EUR/JPY": "EURJPY=X", "BTC": "BTC-USD", "BITCOIN": "BTC-USD", "ETH": "ETH-USD", "ETHEREUM": "ETH-USD", "NIKKEI": "^N225", "日経平均": "^N225", "トヨタ": "7203.T", "NVIDIA": "NVDA"}
    sym = alias.get(sym, sym)
    hdr = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        yf_url = "https://" + "/".join(["://yahoo.com", "v8", "finance", "chart", urllib.parse.quote(sym)])
        r = requests.get(yf_url, params={"interval": "1d", "range": "5d"}, headers=hdr, timeout=8)
        if r.status_code == 200:
            data = r.json()
            res = ((data.get("chart") or {}).get("result") or [None])[0]
            if res and res.get("meta"):
                meta = res["meta"]
                price = meta.get("regularMarketPrice")
                prev = meta.get("chartPreviousClose") or meta.get("previousClose")
                curr = meta.get("currency", "")
                name = meta.get("shortName") or meta.get("longName") or sym
                if price is not None:
                    diff_str = ""
                    if prev:
                        diff = price - prev
                        pct = (diff / prev) * 100
                        sign = "+" if diff >= 0 else ""
                        diff_str = f" / 前日比: {sign}{diff:,.2f} ({sign}{pct:.2f}%)"
                    return f"【リアルタイム市場データ: {name} ({sym})】\n現在値: {price:,.2f} {curr}{diff_str}\n市場状態: {meta.get('marketState', 'UNKNOWN')}"
    except Exception:
        pass

    # 為替フォールバック (Frankfurter API)
    if "JPY" in sym or "USD" in sym:
        try:
            fx_url = "https://" + "/".join(["api.frankfurter.app", "latest"])
            fr = requests.get(fx_url, params={"from": "USD", "to": "JPY,EUR"}, timeout=8).json()
            rates = fr.get("rates") or {}
            if "JPY" in rates:
                return f"【為替レート (Frankfurter / {fr.get('date')})】\n1 USD = {rates['JPY']} JPY"
        except Exception:
            pass

    return f"シンボル '{symbol}' の市場データを取得できませんでした（日本株は 7203.T のように .T を付けて指定してください）。"

def search_wikipedia(query: str, lang: str = "ja") -> str:
    lg = "en" if str(lang).lower().startswith("en") else "ja"
    hdr = {"User-Agent": "NvidiaChatAgent/1.0 (https://github.com)"}
    try:
        api_base = "https://" + lg + "." + "wikipedia.org/w/api.php"
        r = requests.get(api_base, params={"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": 3}, headers=hdr, timeout=8).json()
        hits = (r.get("query") or {}).get("search") or []
        if not hits and lg == "ja":
            return search_wikipedia(query, "en")
        if not hits:
            return f"Wikipediaで '{query}' に一致する記事が見つかりませんでした。"
        out = [f"【Wikipedia検索結果 ({lg}): {query}】"]
        for h in hits:
            title = h["title"]
            sum_url = "https://" + lg + "." + "wikipedia.org/api/rest_v1/page/summary" + "/" + urllib.parse.quote(title)
            sr = requests.get(sum_url, headers=hdr, timeout=8).json()
            extract = sr.get("extract") or re.sub(r"<[^>]+>", "", h.get("snippet", ""))
            page_url = ((sr.get("content_urls") or {}).get("desktop") or {}).get("page") or f"https://{lg}.wikipedia.org/wiki/{urllib.parse.quote(title)}"
            out.append(f"- **[{title}]({page_url})**: {extract}")
        return "\n\n".join(out)
    except Exception as e:
        return f"Wikipedia検索エラー: {e}"

def search_arxiv(query: str) -> str:
    try:
        arxiv_url = "http://" + "export.arxiv.org/api/query"
        r = requests.get(arxiv_url, params={"search_query": f"all:{query}", "start": 0, "max_results": 4, "sortBy": "submittedDate", "sortOrder": "descending"}, timeout=12)
        if r.status_code != 200:
            return f"arXiv APIエラー: {r.status_code}"
        root = ET.fromstring(r.text)
        ns = {"a": "http://w3.org"}
        entries = root.findall("a:entry", ns)
        if not entries:
            return f"arXivで '{query}' に一致する論文が見つかりませんでした。"
        out = [f"【arXiv最新論文検索結果: {query}】"]
        for e in entries:
            title = re.sub(r"\s+", " ", (e.findtext("a:title", "", ns) or "")).strip()
            summary = re.sub(r"\s+", " ", (e.findtext("a:summary", "", ns) or "")).strip()[:450]
            pub = (e.findtext("a:published", "", ns) or "")[:10]
            authors = ", ".join((a.findtext("a:name", "", ns) or "") for a in e.findall("a:author", ns)[:3])
            link = (e.findtext("a:id", "", ns) or "").strip()
            out.append(f"- **[{title}]({link})** ({pub} / 著者: {authors})\n  要旨: {summary}...")
        return "\n\n".join(out)
    except Exception as e:
        return f"arXiv検索エラー: {e}"

def parse_document(name: str, b64_data: str) -> str:
    try:
        raw_b64 = b64_data.split(",", 1)[-1]
        raw_bytes = base64.b64decode(raw_b64)
        ext = os.path.splitext(name.lower())[1]
        if ext == ".pdf":
            reader = PdfReader(io.BytesIO(raw_bytes))
            pages = []
            for idx, page in enumerate(reader.pages):
                txt = (page.extract_text() or "").strip()
                if txt:
                    pages.append(f"--- Page {idx+1} ---\n{txt}")
            full_txt = "\n\n".join(pages)
            return f"【添付PDFファイル: {name} (全{len(reader.pages)}ページ)】\n\n{full_txt[:25000]}"
        else:
            for enc in ("utf-8", "cp932", "shift_jis", "latin-1"):
                try:
                    txt = raw_bytes.decode(enc)
                    break
                except Exception:
                    txt = ""
            if not txt:
                return f"【添付ファイル: {name}】テキストをデコードできませんでした。"
            return f"【添付ファイル: {name}】\n```{ext.lstrip('.')}\n{txt[:25000]}\n```"
    except Exception as e:
        return f"【添付ファイル読込エラー ({name})】: {e}"

def run_python_tool(code: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
        path = f.name
    try:
        res = subprocess.run(["python", path], capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace")
        out = res.stdout.strip()
        err = res.stderr.strip()
        if res.returncode != 0:
            return f"実行エラー (code={res.returncode}):\n{err}"
        return out or "（正常終了・print出力なし）"
    except Exception as e:
        return f"システム実行エラー: {e}"
    finally:
        if os.path.exists(path):
            os.unlink(path)

def read_url(url: str) -> str:
    try:
        if not url.startswith(("http://", "https://")):
            return "エラー: httpまたはhttpsのURLを指定してください"
        r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        r.encoding = r.apparent_encoding or "utf-8"
        if r.status_code != 200:
            return f"HTTPエラー: ステータスコード {r.status_code}"
        raw = r.text
        title_m = re.search(r"<title[^>]*>(.*?)</title>", raw, flags=re.I | re.S)
        title = html.unescape(re.sub(r"<[^>]+>", "", title_m.group(1))).strip() if title_m else "タイトルなし"
        body = re.sub(r"<(script|style|nav|header|footer|aside|noscript)[^>]*>.*?</\1>", " ", raw, flags=re.I | re.S)
        body = re.sub(r"<[^>]+>", " ", body)
        body = re.sub(r"\s+", " ", html.unescape(body)).strip()
        if not body:
            return "本文テキストを抽出できませんでした（JavaScript専用ページの可能性があります）"
        return f"【ページタイトル: {title}】\nURL: {url}\n\n{body[:7000]}"
    except Exception as e:
        return f"ページ読込エラー: {e}"
def get_weather(location: str) -> str:
    try:
        g = requests.get("https://" + ".".join(["geocoding-api", "open-meteo", "com"]) + "/v1/search", params={"name": location, "count": 1, "language": "ja"}, timeout=8).json()
        if not g.get("results"):
            return f"地点 '{location}' が見つかりませんでした"
        loc = g["results"].pop(0)
        lat, lon, name = loc["latitude"], loc["longitude"], loc["name"]
        w = requests.get("https://" + ".".join(["api", "open-meteo", "com"]) + "/v1/forecast", params={"latitude": lat, "longitude": lon, "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max", "timezone": "Asia/Tokyo", "forecast_days": 3}, timeout=8).json()
        d = w["daily"]
        lines = [f"【{name}の天気予報 (Open-Meteo)】"]
        for i in range(len(d["time"])):
            desc = WMO.get(d["weather_code"][i], f"コード{d['weather_code'][i]}")
            lines.append(f"- {d['time'][i]}: {desc} / 最高 {d['temperature_2m_max'][i]}℃ / 最低 {d['temperature_2m_min'][i]}℃ / 降水確率 {d['precipitation_probability_max'][i]}%")
        return "\n".join(lines)
    except Exception as e:
        return f"天気取得エラー: {e}"

def web_search(q: str) -> str:
    for bk in ("lite", "auto"):
        try:
            res = list(DDGS().text(q, region="jp-jp", max_results=4, backend=bk))
            if res:
                return "\n".join(f"- [{r['title']}]({r['href']}): {r['body']}" for r in res)
        except Exception:
            pass
    try:
        rss_url = f"https://google.com{urllib.parse.quote(q)}&hl=ja&gl=JP&ceid=JP:ja"
        r = requests.get(rss_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            root = ET.fromstring(r.text)
            items = [f"- [{(it.findtext('title') or '').strip()}]({(it.findtext('link') or '').strip()})" for it in root.findall(".//item")[:5] if it.findtext("title")]
            if items: return "\n".join(items)
    except Exception as e:
        return f"検索エラー: {e}"
    return "検索結果が見つかりませんでした"
def h_pw(pw: str) -> str:
    return hashlib.sha256(f"nv_salt_{pw}".encode()).hexdigest()

def load_db() -> dict:
    if DATABASE_URL:
        try:
            with _pg_conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT v FROM app_kv WHERE k = 'main_db'")
                row = cur.fetchone()
                if row:
                    d = json.loads(next(iter(row)))
                    if "users" in d:
                        d.setdefault("sessions", {})
                        return d
        except Exception as e:
            print("PG Load Error:", e)
    elif DATA_FILE.exists():
        try:
            d = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            if "users" in d:
                d.setdefault("sessions", {})
                return d
        except Exception:
            pass
    db = {"users": {ADMIN_USER: {"pw": h_pw(ADMIN_PASS), "approved": True, "admin": True}}, "chats": {}, "sessions": {}}
    save_db(db)
    return db

def save_db(db: dict):
    db.setdefault("sessions", {})
    raw = json.dumps(db, ensure_ascii=False)
    if DATABASE_URL:
        try:
            with _pg_conn() as conn, conn.cursor() as cur:
                cur.execute("INSERT INTO app_kv (k, v) VALUES ('main_db', %s) ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v", (raw,))
                conn.commit()
            return
        except Exception as e:
            print("PG Save Error:", e)
    DATA_FILE.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")

def get_user(token: str):
    db = load_db()
    u = SESSIONS.get(token) or db.get("sessions", {}).get(token)
    if not u or u not in db["users"] or not db["users"][u]["approved"]:
        raise HTTPException(401, "未ログインまたは未承認です")
    SESSIONS[token] = u
    return u, db

class AuthReq(BaseModel): username: str; password: str
class ChatReq(BaseModel):
    cid: str
    text: str
    model: str
    effort: str
    image: str = ''
    doc_name: str = ''
    doc_data: str = ''
class ExecReq(BaseModel): code: str

@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(content=Path("index.html").read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})

@app.post("/api/register")
def register(req: AuthReq):
    u, p = req.username.strip(), req.password.strip()
    if len(u) < 2 or len(p) < 4: raise HTTPException(400, "名前2文字以上・パスワード4文字以上")
    db = load_db()
    if u in db["users"]: raise HTTPException(400, "登録済みです")
    db["users"][u] = {"pw": h_pw(p), "approved": False, "admin": False}; save_db(db)
    return {"msg": "申請完了。管理者の承認をお待ちください。"}

@app.post("/api/login")
def login(req: AuthReq):
    db = load_db(); u = db["users"].get(req.username.strip())
    if not u or u["pw"] != h_pw(req.password.strip()): raise HTTPException(401, "名前またはパスワード違い")
    if not u["approved"]: raise HTTPException(403, "管理者の承認待ちです")
    tok = secrets.token_hex(24); uname = req.username.strip(); SESSIONS[tok] = uname; db.setdefault("sessions", {})[tok] = uname; save_db(db)
    return {"token": tok, "username": req.username.strip(), "admin": u["admin"]}

@app.get("/api/me")
def get_me(authorization: str = Header("")):
    u, db = get_user(authorization)
    return {"username": u, "admin": db["users"][u].get("admin", False)}

@app.get("/api/admin/users")
def list_users(authorization: str = Header("")):
    u, db = get_user(authorization)
    if not db["users"][u]["admin"]: raise HTTPException(403, "権限なし")
    return [{"username": k, "approved": v["approved"], "admin": v["admin"]} for k, v in db["users"].items()]

@app.post("/api/admin/approve/{target}")
def approve_user(target: str, authorization: str = Header("")):
    u, db = get_user(authorization)
    if not db["users"][u]["admin"] or target not in db["users"]: raise HTTPException(403, "不可")
    db["users"][target]["approved"] = True; save_db(db); return {"ok": True}

@app.delete("/api/admin/user/{target}")
def del_user(target: str, authorization: str = Header("")):
    u, db = get_user(authorization)
    if not db["users"][u]["admin"] or target == ADMIN_USER: raise HTTPException(403, "不可")
    db["users"].pop(target, None); db["chats"].pop(target, None); save_db(db); return {"ok": True}

class MemReq(BaseModel):
    fact: str

@app.get("/api/memories")
def get_memories(authorization: str = Header("")):
    u, db = get_user(authorization)
    return db.setdefault("memories", {}).get(u, [])

@app.post("/api/memories")
def add_memory(req: MemReq, authorization: str = Header("")):
    u, db = get_user(authorization)
    fact = req.fact.strip()
    if not fact:
        raise HTTPException(400, "内容が空です")
    mems = db.setdefault("memories", {}).setdefault(u, [])
    if fact not in mems:
        mems.append(fact)
        save_db(db)
    return {"ok": True, "memories": mems}

@app.delete("/api/memories/{idx}")
def del_memory(idx: int, authorization: str = Header("")):
    u, db = get_user(authorization)
    mems = db.setdefault("memories", {}).setdefault(u, [])
    if 0 <= idx < len(mems):
        mems.pop(idx)
        save_db(db)
    return {"ok": True, "memories": mems}

@app.get("/api/chats")
def get_chats(authorization: str = Header("")):
    u, db = get_user(authorization); return db["chats"].get(u, {})

@app.post("/api/chats")
def sync_chats(data: dict, authorization: str = Header("")):
    u, db = get_user(authorization); db["chats"][u] = data; save_db(db); return {"ok": True}

@app.post("/api/exec")
def exec_py(req: ExecReq, authorization: str = Header("")):
    get_user(authorization)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(req.code); path = f.name
    try:
        res = subprocess.run(["python", path], capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace")
        return {"out": res.stdout, "err": res.stderr, "code": res.returncode}
    except Exception as e: return {"out": "", "err": str(e), "code": -1}
    finally:
        if os.path.exists(path): os.unlink(path)
class TtsReq(BaseModel):
    text: str
    voice_id: str = "7ca2afba-a719-4f06-9af2-ea2b8e3cf14c"

@app.post("/api/tts")
def tts_api(req: TtsReq, authorization: str = Header("")):
    get_user(authorization)
    txt = req.text.strip()[:1500]
    if not txt:
        raise HTTPException(400, "empty")
    c_key = (os.getenv("CARTESIA_API_KEY") or "").strip()
    if not c_key:
        raise HTTPException(500, "CARTESIA_API_KEY 未設定")
    vid = (os.getenv("CARTESIA_VOICE_ID") or req.voice_id).strip()
    try:
        from cartesia import Cartesia
        client = Cartesia(api_key=c_key, base_url="https://" + "api.cartesia.ai")
        resp = client.tts.generate(
            model_id="sonic-3.6",
            transcript=txt,
            voice=vid,
            language="ja",
            output_format={
                "container": "wav",
                "encoding": "pcm_s16le",
                "sample_rate": 44100
            },
            generation_config={
                "speed": 1,
                "volume": 1
            }
        )
        if hasattr(resp, "write_to_file"):
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                tmp_wav = tf.name
            try:
                resp.write_to_file(tmp_wav)
                with open(tmp_wav, "rb") as af:
                    audio_data = af.read()
            finally:
                if os.path.exists(tmp_wav):
                    os.unlink(tmp_wav)
        elif hasattr(resp, "read"):
            audio_data = resp.read()
        elif isinstance(resp, (bytes, bytearray)):
            audio_data = bytes(resp)
        else:
            audio_data = b"".join(resp)

        if audio_data:
            return Response(content=audio_data, media_type="audio/wav")
        raise HTTPException(500, "Cartesia音声データが空です")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Cartesia SDK Error: {type(e).__name__}: {e}")

class InquiryReq(BaseModel):
    category: str
    subject: str
    message: str

class ReplyReq(BaseModel):
    status: str
    reply: str

@app.get("/contact", response_class=HTMLResponse)
def contact_page():
    return HTMLResponse(content=Path("contact.html").read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})

@app.get("/api/inquiries")
def get_inquiries(authorization: str = Header("")):
    u, db = get_user(authorization)
    is_admin = db["users"][u].get("admin", False)
    items = db.setdefault("inquiries", [])
    if is_admin:
        return {"admin": True, "username": u, "items": items}
    return {"admin": False, "username": u, "items": [x for x in items if x.get("user") == u]}

@app.post("/api/inquiries")
def create_inquiry(req: InquiryReq, authorization: str = Header("")):
    u, db = get_user(authorization)
    subj, msg = req.subject.strip(), req.message.strip()
    if not subj or not msg:
        raise HTTPException(400, "件名と内容を入力してください")
    items = db.setdefault("inquiries", [])
    item = {
        "id": uuid.uuid4().hex[:10],
        "user": u,
        "category": req.category.strip() or "その他",
        "subject": subj,
        "message": msg,
        "status": "未対応",
        "reply": "",
        "created_at": f"{datetime.now():%Y-%m-%d %H:%M}",
        "updated_at": ""
    }
    items.insert(0, item)
    save_db(db)
    return {"ok": True, "item": item}

@app.post("/api/admin/inquiries/{inq_id}")
def reply_inquiry(inq_id: str, req: ReplyReq, authorization: str = Header("")):
    u, db = get_user(authorization)
    if not db["users"][u].get("admin", False):
        raise HTTPException(403, "管理者権限が必要です")
    for it in db.setdefault("inquiries", []):
        if it.get("id") == inq_id:
            it["status"] = req.status
            it["reply"] = req.reply.strip()
            it["updated_at"] = f"{datetime.now():%Y-%m-%d %H:%M}"
            save_db(db)
            return {"ok": True}
    raise HTTPException(404, "対象の問い合わせが見つかりません")

@app.delete("/api/admin/inquiries/{inq_id}")
def delete_inquiry(inq_id: str, authorization: str = Header("")):
    u, db = get_user(authorization)
    if not db["users"][u].get("admin", False):
        raise HTTPException(403, "管理者権限が必要です")
    db["inquiries"] = [it for it in db.setdefault("inquiries", []) if it.get("id") != inq_id]
    save_db(db)
    return {"ok": True}

@app.post("/api/chat_stream")
def chat_stream(req: ChatReq, authorization: str = Header("")):
    u, db = get_user(authorization)
    api_key = (os.getenv("NVIDIA_API_KEY") or "").strip()
    invoke_url = (os.getenv("NVIDIA_INVOKE_URL") or ("https://" + "integrate.api." + "://nvidia.com")).strip()
    if not api_key:
        raise HTTPException(500, "NVIDIA_API_KEY 未設定")

    uchats = db["chats"].setdefault(u, {})
    umems = db.setdefault("memories", {}).get(u, [])
    mem_txt = "\n【ユーザーに関する長期記憶（常に前提として考慮すること）】\n" + "\n".join(f"- {m}" for m in umems) if umems else ""
    sys_p = (
        f"今日は{datetime.now():%Y年%m月%d日}です。天気や気温は get_weather ツールを、最新ニュースや調べ物は web_search ツールを、"
        "URLの内容を尋ねられた場合や検索結果の詳細を読む場合は read_url ツールを、複雑な計算や数値検証・日付計算が必要な場合は run_python ツールを、"
        "用語や人物の定義は search_wikipedia を、学術論文や最新AI研究は search_arxiv ツールを、株価・為替・暗号資産の現在価格は get_market_data ツールを必ず呼び出して日本語で回答してください。"
        "また、ユーザーが自身の属性・好み・使用技術・今後の会話でも覚えておくべき前提を話した場合は save_memory ツールで保存し、訂正や忘却を求めた場合は delete_memory ツールを使ってください。"
        + mem_txt
    )
    cobj = uchats.setdefault(req.cid, {"title": req.text[:14], "msgs": [{"role": "system", "content": sys_p}], "turns": []})
    if cobj["msgs"] and cobj["msgs"].get("role") == "system":
        cobj["msgs"]["content"] = sys_p
    doc_prefix = ""
    if req.doc_name and req.doc_data:
        doc_prefix = parse_document(req.doc_name, req.doc_data) + "\n\n【ユーザーの指示】\n"
    actual_text = doc_prefix + (req.text or ("このドキュメントの内容を分かりやすく要約・解析してください。" if req.doc_name else ""))

    if req.image:
        v_models = ("nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", "google/paligemma")
        if req.model not in v_models:
            req.model = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
        u_content = [
            {"type": "text", "text": actual_text or "この画像について詳しく説明してください。"},
            {"type": "image_url", "image_url": {"url": req.image}}
        ]
        cobj["msgs"].append({"role": "user", "content": u_content})
    else:
        cobj["msgs"].append({"role": "user", "content": actual_text})

    def gen():
        hdr = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "text/event-stream"}
        t0, ta, tn, pt, ct, logs, rall, ans = time.perf_counter(), 0.0, 0.0, 0, 0, [], "", ""
        try:
            for _ in range(3):
                has_img = any(isinstance(m.get("content"), list) for m in cobj["msgs"])
                pay = {"model": req.model, "messages": cobj["msgs"], "max_tokens": 4096, "stream": True, "stream_options": {"include_usage": True}, "temperature": 0.5}
                if not has_img:
                    pay["tools"] = TOOLS
                    pay["tool_choice"] = "auto"
                if "nemotron" not in req.model:
                    pay["reasoning_effort"] = req.effort
                r = requests.post(invoke_url, headers=hdr, json=pay, stream=True, timeout=120)
                if r.status_code != 200:
                    cobj["msgs"].pop()
                    yield f"data: {json.dumps({'type':'err','msg':f'API Error {r.status_code}: {r.text[:150]}'})}\n\n"
                    return

                cnt, rsn, usg, tc_map = "", "", {}, {}
                for line in r.iter_lines():
                    if not line or not (s := line.decode("utf-8")).startswith("data: "):
                        continue
                    if (d := s[6:].strip()) == "[DONE]":
                        break
                    try:
                        chk = json.loads(d)
                        usg = chk.get("usage") or usg
                        dlt = next(iter(chk.get("choices") or []), {}).get("delta") or {}
                        if rp := dlt.get("reasoning_content"):
                            ta = ta or (time.perf_counter() - t0)
                            rsn += rp
                            yield f"data: {json.dumps({'type':'r','text':rp})}\n\n"
                        if tcs := dlt.get("tool_calls"):
                            for tc in tcs:
                                idx = tc.get("index", 0)
                                entry = tc_map.setdefault(idx, {"id": "", "name": "", "args": ""})
                                if tc.get("id"):
                                    entry["id"] = tc["id"]
                                fn = tc.get("function") or {}
                                if fn.get("name"):
                                    entry["name"] = fn["name"]
                                if fn.get("arguments"):
                                    entry["args"] += fn["arguments"]
                        if cp := dlt.get("content"):
                            ta = ta or (time.perf_counter() - t0)
                            tn = tn or (time.perf_counter() - t0)
                            cnt += cp
                            if not cnt.strip().startswith("[SEARCH:"):
                                yield f"data: {json.dumps({'type':'c','text':cp})}\n\n"
                    except Exception:
                        pass

                pt += usg.get("prompt_tokens", 0)
                ct += usg.get("completion_tokens", 0) or int((len(cnt) + len(rsn)) * 0.7)
                if rsn:
                    rall += rsn + "\n\n"

                if tc_map:
                    asst_tcs, tool_msgs = [], []
                    for idx in sorted(tc_map.keys()):
                        entry = tc_map[idx]
                        tid = entry["id"] or f"call_{idx}"
                        fname = entry["name"] or "web_search"
                        raw_args = entry["args"].strip()
                        try:
                            parsed = json.loads(raw_args)
                            clean_args = json.dumps(parsed, ensure_ascii=False)
                        except Exception:
                            parsed = {"query": raw_args, "location": raw_args}
                            clean_args = json.dumps(parsed, ensure_ascii=False)

                        if fname == "save_memory":
                            fact = (parsed.get("fact") or raw_args).strip()
                            mems = db.setdefault("memories", {}).setdefault(u, [])
                            if fact and fact not in mems:
                                mems.append(fact)
                                save_db(db)
                            sres = f"長期記憶に保存しました: {fact}"
                            logs.append({"q": f"🧠 記憶保存: {fact}", "res": sres})
                            yield f"data: {json.dumps({'type':'s','q':f'🧠 記憶保存: {fact}','res':sres})}\n\n"
                        elif fname == "delete_memory":
                            kw = (parsed.get("keyword") or raw_args).strip()
                            mems = db.setdefault("memories", {}).setdefault(u, [])
                            before = len(mems)
                            db["memories"][u] = [m for m in mems if kw not in m]
                            save_db(db)
                            sres = f"キーワード '{kw}' に一致する記憶を {before - len(db['memories'][u])} 件削除しました。"
                            logs.append({"q": f"🧠 記憶削除: {kw}", "res": sres})
                            yield f"data: {json.dumps({'type':'s','q':f'🧠 記憶削除: {kw}','res':sres})}\n\n"
                        elif fname == "get_market_data":
                            msym = parsed.get("symbol") or parsed.get("query") or raw_args
                            yield f"data: {json.dumps({'type':'status','msg':f'📈 市場データ取得中: {msym}'})}\n\n"
                            sres = get_market_data(msym)
                            logs.append({"q": f"📈 市場: {msym}", "res": sres})
                            yield f"data: {json.dumps({'type':'s','q':f'📈 市場: {msym}','res':sres})}\n\n"
                        elif fname == "search_wikipedia":
                            wq = parsed.get("query") or raw_args
                            wlang = parsed.get("lang") or "ja"
                            yield f"data: {json.dumps({'type':'status','msg':f'📚 Wikipedia検索中: {wq}'})}\n\n"
                            sres = search_wikipedia(wq, wlang)
                            logs.append({"q": f"📚 Wikipedia: {wq}", "res": sres})
                            yield f"data: {json.dumps({'type':'s','q':f'📚 Wikipedia: {wq}','res':sres})}\n\n"
                        elif fname == "search_arxiv":
                            aq = parsed.get("query") or raw_args
                            yield f"data: {json.dumps({'type':'status','msg':f'🎓 arXiv論文検索中: {aq}'})}\n\n"
                            sres = search_arxiv(aq)
                            logs.append({"q": f"🎓 arXiv: {aq}", "res": sres})
                            yield f"data: {json.dumps({'type':'s','q':f'🎓 arXiv: {aq}','res':sres})}\n\n"
                        elif fname == "run_python":
                            py_code = parsed.get("code") or parsed.get("query") or raw_args
                            yield f"data: {json.dumps({'type':'status','msg':'🐍 Python自律計算・検証中...'})}\n\n"
                            sres = run_python_tool(py_code)
                            log_md = f"**実行コード:**\n```python\n{py_code}\n```\n**計算結果:**\n```text\n{sres}\n```"
                            logs.append({"q": "🐍 Python自律計算", "res": log_md})
                            yield f"data: {json.dumps({'type':'s','q':'🐍 Python自律計算','res':log_md})}\n\n"
                        elif fname == "read_url":
                            target_url = parsed.get("url") or parsed.get("query") or raw_args
                            yield f"data: {json.dumps({'type':'status','msg':f'📖 ページ読込中: {target_url}'})}\n\n"
                            sres = read_url(target_url)
                            logs.append({"q": f"📖 読込: {target_url}", "res": sres[:500] + ("..." if len(sres) > 500 else "")})
                            yield f"data: {json.dumps({'type':'s','q':f'📖 読込: {target_url}','res':sres[:500] + ("" if len(sres) <= 500 else "...")})}\n\n"
                        elif fname == "get_weather":
                            loc = parsed.get("location") or parsed.get("query") or "Yokohama"
                            yield f"data: {json.dumps({'type':'status','msg':f'☀️ 天気取得中: {loc}'})}\n\n"
                            sres = get_weather(loc)
                            logs.append({"q": f"天気: {loc}", "res": sres})
                            yield f"data: {json.dumps({'type':'s','q':f'天気: {loc}','res':sres})}\n\n"
                        else:
                            q = parsed.get("query") or raw_args
                            yield f"data: {json.dumps({'type':'status','msg':f'🌐 Web検索中: {q}'})}\n\n"
                            sres = web_search(q)
                            logs.append({"q": q, "res": sres})
                            yield f"data: {json.dumps({'type':'s','q':q,'res':sres})}\n\n"

                        asst_tcs.append({"id": tid, "type": "function", "function": {"name": fname, "arguments": clean_args}})
                        tool_msgs.append({"role": "tool", "tool_call_id": tid, "content": sres})
                    cobj["msgs"].append({"role": "assistant", "content": None, "tool_calls": asst_tcs})
                    cobj["msgs"].extend(tool_msgs)
                    continue

                if m := re.search(r"\[SEARCH:\s*(.+?)\]", cnt):
                    q = m.group(1).strip()
                    yield f"data: {json.dumps({'type':'status','msg':f'🌐 Web検索中: {q}'})}\n\n"
                    sres = web_search(q)
                    logs.append({"q": q, "res": sres})
                    yield f"data: {json.dumps({'type':'s','q':q,'res':sres})}\n\n"
                    cobj["msgs"] += [{"role": "assistant", "content": f"[SEARCH: {q}]"}, {"role": "user", "content": f"検索結果:\n{sres}"}]
                    continue

                ans = cnt
                cobj["msgs"].append({"role": "assistant", "content": ans})
                break

            dt = time.perf_counter() - t0
            st = f"📊 入力:{pt} | 出力:{ct} | ⏱ 思考:{max(tn-ta,0.0) if tn else 0.0:.1f}s | 総:{dt:.2f}s | ⚡ {ct/max(dt-ta,0.01):.1f} tok/s"
            q_label = (f"[📄 {req.doc_name}] " if req.doc_name else "") + ("[🖼️ 画像添付] " if req.image else "") + req.text
            turn = {"q": q_label.strip(), "img": req.image, "a": ans, "r": rall.strip(), "s": logs, "m": f"{req.model.split('/')[-1]}|{req.effort}", "st": st}
            cobj["turns"].append(turn)
            save_db(db)
            yield f"data: {json.dumps({'type':'done','turn':turn})}\n\n"
        except Exception as ex:
            yield f"data: {json.dumps({'type':'err','msg':str(ex)})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")






