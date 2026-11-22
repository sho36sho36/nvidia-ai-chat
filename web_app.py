import os, re, json, time, uuid, hashlib, secrets, subprocess, tempfile, requests
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

TOOLS = [{
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "最新の天気、ニュース、日付、人物、価格、専門知識などをインターネットでリアルタイム検索する。",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "検索キーワード"}},
            "required": ["query"]
        }
    }
}]

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

def web_search(q: str) -> str:
    try:
        res = DDGS().text(q, region="jp-jp", max_results=4)
        return "\n".join(f"- [{r['title']}]({r['href']}): {r['body']}" for r in res) or "結果なし"
    except Exception as e: return f"検索エラー: {e}"

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
    invoke_url = (os.getenv("NVIDIA_INVOKE_URL") or ("https://" + "://nvidia.com" + "/v1/chat/completions")).strip()
    if not api_key: raise HTTPException(500, "NVIDIA_API_KEY 未設定")

    uchats = db["chats"].setdefault(u, {})
    sys_p = f"今日は{datetime.now():%Y年%m月%d日}です。最新情報や天気・ニュースが関係する場合は必ず web_search ツールを呼び出して検索し、結果を元に日本語で回答してください。"
    cobj = uchats.setdefault(req.cid, {"title": req.text[:14], "msgs": [{"role": "system", "content": sys_p}], "turns": []})
    cobj["msgs"].append({"role": "user", "content": req.text})

    def gen():
        hdr = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "text/event-stream"}
        t0, ta, tn, pt, ct, logs, rall, ans = time.perf_counter(), 0.0, 0.0, 0, 0, [], "", ""
        try:
            for _ in range(3):
                pay = {"model": req.model, "messages": cobj["msgs"], "max_tokens": 4096, "stream": True, "stream_options": {"include_usage": True}, "temperature": 0.5, "tools": TOOLS, "tool_choice": "auto"}
                if "nemotron" not in req.model: pay["reasoning_effort"] = req.effort
                r = requests.post(invoke_url, headers=hdr, json=pay, stream=True, timeout=120)
                if r.status_code != 200:
                    cobj["msgs"].pop()
                    yield f"data: {json.dumps({'type':'err','msg':f'API Error {r.status_code}: {r.text[:120]}'})}\n\n"; return
                cnt, rsn, usg, tc_id, tc_name, tc_args = "", "", {}, "", "", ""
                for line in r.iter_lines():
                    if not line or not (s := line.decode("utf-8")).startswith("data: "): continue
                    if (d := s[6:].strip()) == "[DONE]": break
                    try:
                        chk = json.loads(d); usg = chk.get("usage") or usg
                        dlt = next(iter(chk.get("choices") or []), {}).get("delta") or {}
                        if rp := dlt.get("reasoning_content"):
                            ta = ta or (time.perf_counter() - t0); rsn += rp
                            yield f"data: {json.dumps({'type':'r','text':rp})}\n\n"
                        if tcs := dlt.get("tool_calls"):
                            tc = next(iter(tcs), {})
                            tc_id = tc.get("id") or tc_id
                            fn = tc.get("function") or {}
                            tc_name = fn.get("name") or tc_name
                            tc_args += fn.get("arguments") or ""
                        if cp := dlt.get("content"):
                            ta = ta or (time.perf_counter() - t0); tn = tn or (time.perf_counter() - t0); cnt += cp
                            if not cnt.strip().startswith("[SEARCH:"):
                                yield f"data: {json.dumps({'type':'c','text':cp})}\n\n"
                    except Exception: pass
                pt += usg.get("prompt_tokens", 0); ct += usg.get("completion_tokens", 0) or int((len(cnt)+len(rsn))*0.7)
                if rsn: rall += rsn + "\n\n"

                if tc_name == "web_search" and tc_args:
                    try: q = json.loads(tc_args).get("query", tc_args)
                    except Exception: q = tc_args
                    yield f"data: {json.dumps({'type':'status','msg':f'🌐 Web検索中: {q}'})}\n\n"
                    sres = web_search(q); logs.append({"q": q, "res": sres})
                    yield f"data: {json.dumps({'type':'s','q':q,'res':sres})}\n\n"
                    cobj["msgs"].append({"role": "assistant", "content": None, "tool_calls": [{"id": tc_id or "call_1", "type": "function", "function": {"name": "web_search", "arguments": tc_args}}]})
                    cobj["msgs"].append({"role": "tool", "tool_call_id": tc_id or "call_1", "content": sres})
                    continue

                if m := re.search(r"\[SEARCH:\s*(.+?)\]", cnt):
                    q = m.group(1).strip()
                    yield f"data: {json.dumps({'type':'status','msg':f'🌐 Web検索中: {q}'})}\n\n"
                    sres = web_search(q); logs.append({"q": q, "res": sres})
                    yield f"data: {json.dumps({'type':'s','q':q,'res':sres})}\n\n"
                    cobj["msgs"] += [{"role": "assistant", "content": f"[SEARCH: {q}]"}, {"role": "user", "content": f"検索結果:\n{sres}"}]
                    continue

                ans = cnt; cobj["msgs"].append({"role": "assistant", "content": ans}); break
            dt = time.perf_counter() - t0
            st = f"📊 入力:{pt} | 出力:{ct} | ⏱ 思考:{max(tn-ta,0.0) if tn else 0.0:.1f}s | 総:{dt:.2f}s | ⚡ {ct/max(dt-ta,0.01):.1f} tok/s"
            turn = {"q": req.text, "a": ans, "r": rall.strip(), "s": logs, "m": f"{req.model.split('/')[-1]}|{req.effort}", "st": st}
            cobj["turns"].append(turn); save_db(db)
            yield f"data: {json.dumps({'type':'done','turn':turn})}\n\n"
        except Exception as ex: yield f"data: {json.dumps({'type':'err','msg':str(ex)})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
