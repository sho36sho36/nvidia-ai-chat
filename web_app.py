import os, re, json, html, time, uuid, hashlib, secrets, subprocess, tempfile, urllib.parse, xml.etree.ElementTree as ET, requests
from pathlib import Path
from datetime import datetime
from ddgs import DDGS
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel

app = FastAPI()
app.add_middleware(GZipMiddleware, minimum_size=500)
DATA_FILE = Path("web_data.json")
ADMIN_USER, ADMIN_PASS = "sho36", "shoma0121"
SESSIONS = {}

TOOLS = [\n    {
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
    if DATA_FILE.exists():
        try:
            d = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            if "users" in d: return d
        except Exception: pass
    db = {"users": {ADMIN_USER: {"pw": h_pw(ADMIN_PASS), "approved": True, "admin": True}}, "chats": {}}
    save_db(db); return db

def save_db(db: dict):
    DATA_FILE.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")

def get_user(token: str):
    u = SESSIONS.get(token); db = load_db()
    if not u or u not in db["users"] or not db["users"][u]["approved"]:
        raise HTTPException(401, "未ログインまたは未承認です")
    return u, db

class AuthReq(BaseModel): username: str; password: str
class ChatReq(BaseModel): cid: str; text: str; model: str; effort: str
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
    tok = secrets.token_hex(24); SESSIONS[tok] = req.username.strip()
    return {"token": tok, "username": req.username.strip(), "admin": u["admin"]}

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
@app.post("/api/chat_stream")
def chat_stream(req: ChatReq, authorization: str = Header("")):
    u, db = get_user(authorization)
    api_key = (os.getenv("NVIDIA_API_KEY") or "").strip()
    invoke_url = (os.getenv("NVIDIA_INVOKE_URL") or ("https://" + "integrate.api." + "://nvidia.com")).strip()
    if not api_key:
        raise HTTPException(500, "NVIDIA_API_KEY 未設定")

    uchats = db["chats"].setdefault(u, {})
    sys_p = f"今日は{datetime.now():%Y年%m月%d日}です。天気や気温は get_weather ツールを、最新ニュースや調べ物は web_search ツールを、URLの内容を尋ねられた場合や検索結果の詳細を読む場合は read_url ツールを必ず呼び出して日本語で回答してください。"
    cobj = uchats.setdefault(req.cid, {"title": req.text[:14], "msgs": [{"role": "system", "content": sys_p}], "turns": []})
    cobj["msgs"].append({"role": "user", "content": req.text})

    def gen():
        hdr = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "text/event-stream"}
        t0, ta, tn, pt, ct, logs, rall, ans = time.perf_counter(), 0.0, 0.0, 0, 0, [], "", ""
        try:
            for _ in range(3):
                pay = {"model": req.model, "messages": cobj["msgs"], "max_tokens": 4096, "stream": True, "stream_options": {"include_usage": True}, "temperature": 0.5, "tools": TOOLS, "tool_choice": "auto"}
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

                        if fname == "read_url":
                            target_url = parsed.get("url") or parsed.get("query") or raw_args
                            yield f"data: {json.dumps({'type':'status','msg':f'📖 ページ読込中: {target_url}'})}\n\n"
                            sres = read_url(target_url)
                            logs.append({"q": f"📖 読込: {target_url}", "res": sres[:500] + ("..." if len(sres) > 500 else "")})
                            yield f"data: {json.dumps({'type':'s','q':f'📖 読込: {target_url}','res':sres[:500] + ('...' if len(sres) > 500 else '')})}\n\n"
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
            turn = {"q": req.text, "a": ans, "r": rall.strip(), "s": logs, "m": f"{req.model.split('/')[-1]}|{req.effort}", "st": st}
            cobj["turns"].append(turn)
            save_db(db)
            yield f"data: {json.dumps({'type':'done','turn':turn})}\n\n"
        except Exception as ex:
            yield f"data: {json.dumps({'type':'err','msg':str(ex)})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")




