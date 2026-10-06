#!/usr/bin/env python3
"""Game Time: kids ask for internet time, a parent approves, UniFi blocking
policies are switched off for that long and back on when it runs out.

    /          the kid page: status per profile, "ask for 30 min / 1 h / 2 h"
    /parent    PIN-protected: approve/deny requests, grant/end time, toggle
               any policy directly, and define profiles (name -> policies)

A profile is a person/device plus the UniFi firewall policies that normally
block it. "Time granted" = those policies disabled until the timer ends; the
scheduler re-enables them. Grants survive restarts (state.json).

Config (env, see .env.example): UNIFI_HOST, UNIFI_API_KEY, UNIFI_SITE,
PARENT_PIN, SECRET, NTFY_URL (optional push for new requests), PUBLIC_URL,
DATA_DIR, UNIFI_MOCK=1 (demo without a gateway).
"""
import asyncio
import contextlib
import datetime as dt
import hmac
import hashlib
import json
import logging
import os
import secrets
import uuid
import zoneinfo
from typing import Optional

import httpx
from fastapi import Cookie, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import unifi

log = logging.getLogger("gametime")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(HERE, "data"))
STATE_PATH = os.path.join(DATA_DIR, "state.json")
PARENT_PIN = os.environ.get("PARENT_PIN", "")
SECRET = os.environ.get("SECRET") or secrets.token_hex(32)
NTFY_URL = os.environ.get("NTFY_URL", "").strip()
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://192.168.0.190:8085").rstrip("/")
TZ = zoneinfo.ZoneInfo(os.environ.get("TZ", "America/Los_Angeles"))
COOKIE = "gt_parent"
MAX_MINUTES = int(os.environ.get("MAX_MINUTES", "240"))
REQUEST_TTL_MIN = 120          # pending requests older than this expire
TICK_SECONDS = 15

if not PARENT_PIN:
    raise SystemExit("PARENT_PIN is not set (run setup.sh)")


def now():
    return dt.datetime.now(dt.timezone.utc)


def iso(t):
    return t.isoformat(timespec="seconds")


def parse(s):
    return dt.datetime.fromisoformat(s)


def local_clock(t):
    return t.astimezone(TZ).strftime("%-I:%M %p")


def _clock(naive_local, now_local):
    """'9:30 PM' today, 'Tue 7:00 AM' on another day, None for None/indefinite."""
    if naive_local is None:
        return None
    fmt = "%-I:%M %p" if naive_local.date() == now_local.date() else "%a %-I:%M %p"
    return naive_local.strftime(fmt)


# ---------------------------------------------------------------- state ----
class State:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.d = {"profiles": [], "grants": {}, "requests": [], "log": []}
        os.makedirs(DATA_DIR, exist_ok=True)
        if os.path.exists(STATE_PATH):
            with open(STATE_PATH) as f:
                self.d.update(json.load(f))

    def save(self):
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.d, f, indent=1)
        os.replace(tmp, STATE_PATH)

    def note(self, msg):
        log.info(msg)
        self.d["log"].append({"ts": iso(now()), "msg": msg})
        del self.d["log"][:-200]

    def profile(self, pid):
        for p in self.d["profiles"]:
            if p["id"] == pid:
                return p
        raise HTTPException(404, "no such profile")

    def request(self, rid):
        for r in self.d["requests"]:
            if r["id"] == rid:
                return r
        raise HTTPException(404, "no such request")

    def pending_for(self, pid):
        return next((r for r in self.d["requests"] if r["profile_id"] == pid and r["status"] == "pending"), None)


state = State()
net = unifi.from_env()
MOCK = isinstance(net, unifi.MockUniFi)


# ------------------------------------------------------------- policies ----
async def apply(profile, open_, reason):
    """Set every policy of the profile: open_=True disables the blockers."""
    errors = []
    for pid in profile["policy_ids"]:
        try:
            await net.set_enabled(pid, not open_)
        except unifi.UniFiError as e:
            errors.append(str(e))
    state.note(f"{profile['name']}: {'OPEN' if open_ else 'BLOCKED'} ({reason})"
               + (f" — errors: {'; '.join(errors)}" if errors else ""))
    if errors:
        raise HTTPException(502, "; ".join(errors))


async def grant(profile, minutes, by):
    """Start or extend a grant. Called with state.lock held."""
    minutes = max(1, min(int(minutes), MAX_MINUTES))
    g = state.d["grants"].get(profile["id"])
    base = now()
    if g and parse(g["until"]) > base:
        base = parse(g["until"])
    until = base + dt.timedelta(minutes=minutes)
    state.d["grants"][profile["id"]] = {"until": iso(until), "by": by, "started": g["started"] if g else iso(now())}
    state.save()
    await apply(profile, True, f"{minutes} min by {by}, until {local_clock(until)}")
    state.save()
    return until


async def end(profile, reason):
    """Called with state.lock held."""
    state.d["grants"].pop(profile["id"], None)
    state.save()
    await apply(profile, False, reason)
    state.save()


async def notify(title, body, click=None):
    if not NTFY_URL:
        return
    headers = {"Title": title, "Tags": "video_game"}
    if click:
        headers["Click"] = click
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(NTFY_URL, content=body.encode(), headers=headers)
    except httpx.HTTPError as e:
        log.warning("ntfy failed: %s", e)


async def scheduler():
    # On startup: re-assert any grant that is still running (the server may have
    # restarted mid-grant). Expired grants are handled by the first tick.
    async with state.lock:
        for pid, g in list(state.d["grants"].items()):
            if parse(g["until"]) > now():
                with contextlib.suppress(HTTPException, Exception):
                    await apply(state.profile(pid), True, "restart: grant still running")
    while True:
        try:
            async with state.lock:
                t = now()
                for pid, g in list(state.d["grants"].items()):
                    if parse(g["until"]) <= t:
                        try:
                            await end(state.profile(pid), "time's up")
                        except Exception as e:  # keep the grant so we retry next tick
                            log.warning("could not end grant for %s: %s", pid, e)
                            state.d["grants"][pid] = g
                            state.save()
                for r in state.d["requests"]:
                    if r["status"] == "pending" and parse(r["created"]) + dt.timedelta(minutes=REQUEST_TTL_MIN) < t:
                        r["status"] = "expired"
                        state.save()
                del state.d["requests"][:-100]
        except Exception as e:
            log.exception("scheduler tick failed: %s", e)
        await asyncio.sleep(TICK_SECONDS)


@contextlib.asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(scheduler())
    try:
        v = await net.version()
        log.info("UniFi Network %s via %s", v, getattr(net, "host", "mock"))
    except Exception as e:
        log.warning("UniFi not reachable at startup: %s", e)
    yield
    task.cancel()
    await net.close()


app = FastAPI(title="Game Time", lifespan=lifespan, docs_url=None, redoc_url=None)


# ----------------------------------------------------------------- auth ----
def session_token():
    return hmac.new(SECRET.encode(), b"parent-session", hashlib.sha256).hexdigest()


def is_parent(cookie):
    return bool(cookie) and hmac.compare_digest(cookie, session_token())


def require_parent(gt_parent: Optional[str] = Cookie(default=None)):
    if not is_parent(gt_parent):
        raise HTTPException(401, "parent PIN required")


_failed = {"n": 0}


def who(req: Request):
    """'192.168.0.42 (iPhone)' — the device behind a login attempt, for the log."""
    ip = req.headers.get("x-forwarded-for", "").split(",")[0].strip() or (req.client.host if req.client else "?")
    ua = req.headers.get("user-agent", "")
    kind = next((k for k in ("iPhone", "iPad", "Android", "Macintosh", "Windows", "Linux") if k in ua), "unknown device")
    return f"{ip} ({kind})"


@app.post("/api/login")
async def login(req: Request, resp: Response):
    body = await req.json()
    pin = str(body.get("pin", ""))
    if _failed["n"] >= 5:
        await asyncio.sleep(3)   # crude brute-force brake
    if not hmac.compare_digest(pin, PARENT_PIN):
        _failed["n"] += 1
        async with state.lock:
            state.note(f"WRONG PIN attempt #{_failed['n']} from {who(req)}")
            state.save()
        if _failed["n"] == 5:
            await notify("Game Time: 5 wrong PIN attempts", f"From {who(req)}", f"{PUBLIC_URL}/parent")
        await asyncio.sleep(1)
        raise HTTPException(401, "wrong PIN")
    _failed["n"] = 0
    async with state.lock:
        state.note(f"parent login from {who(req)}")
        state.save()
    await notify("Game Time: parent login", f"From {who(req)}. Not you? Change PARENT_PIN in .env.", f"{PUBLIC_URL}/parent")
    resp.set_cookie(COOKIE, session_token(), max_age=60 * 60 * 24 * 365, httponly=True, samesite="lax")
    return {"ok": True}


@app.post("/api/logout")
async def logout(resp: Response):
    resp.delete_cookie(COOKIE)
    return {"ok": True}


# --------------------------------------------------------------- public ----
async def live_policies():
    try:
        return {p["id"]: p for p in await net.list_policies()}, None
    except unifi.UniFiError as e:
        return {}, str(e)


def profile_view(p, pols, t):
    g = state.d["grants"].get(p["id"])
    until = parse(g["until"]) if g else None
    active = bool(until and until > t)
    its = [pols.get(pid) or {"id": pid, "name": "(missing policy)", "enabled": None} for pid in p["policy_ids"]]
    # Live truth from the gateway + the rules' own schedules: a rule only blocks
    # while it is enabled AND its schedule window is running.
    known = [x for x in its if x.get("enabled") is not None]
    tl = t.astimezone(TZ).replace(tzinfo=None)
    blocking = [x["name"] for x in known if unifi.blocking_now(x, tl)]
    nxt = unifi.next_window(known, tl)
    until_block = unifi.blocked_until(known, tl) if blocking else None
    for x in its:
        x["blocking_now"] = unifi.blocking_now(x, tl) if x.get("enabled") is not None else None
    pend = state.pending_for(p["id"])
    return {
        "id": p["id"], "name": p["name"], "icon": p.get("icon", "🎮"),
        "max_minutes": p.get("max_minutes", MAX_MINUTES),
        "grant": {"until": iso(until), "until_local": local_clock(until),
                  "minutes_left": max(0, int((until - t).total_seconds() // 60) + 1), "by": g["by"]} if active else None,
        "open": not blocking, "blocking": blocking,
        "blocked_until": _clock(until_block, tl), "next_block": _clock(nxt[0], tl) if nxt else None,
        "policies": its,
        "pending": {"id": pend["id"], "minutes": pend["minutes"], "note": pend["note"], "created": pend["created"]} if pend else None,
    }


@app.get("/api/status")
async def status(gt_parent: Optional[str] = Cookie(default=None)):
    pols, err = await live_policies()
    t = now()
    return {"now": iso(t), "mock": MOCK, "unifi_error": err, "parent": is_parent(gt_parent),
            "profiles": [profile_view(p, pols, t) for p in state.d["profiles"]]}


@app.post("/api/request")
async def make_request(req: Request):
    body = await req.json()
    minutes = int(body.get("minutes", 30))
    note = str(body.get("note", ""))[:140]
    async with state.lock:
        p = state.profile(str(body.get("profile_id")))
        minutes = max(5, min(minutes, p.get("max_minutes", MAX_MINUTES)))
        old = state.pending_for(p["id"])
        if old:
            old["status"] = "replaced"
        r = {"id": uuid.uuid4().hex[:8], "profile_id": p["id"], "minutes": minutes, "note": note,
             "created": iso(now()), "status": "pending"}
        state.d["requests"].append(r)
        state.note(f"{p['name']}: asked for {minutes} min" + (f' — "{note}"' if note else ""))
        state.save()
    await notify(f"{p['name']} is asking for {minutes} min", note or "Open Game Time to approve or deny.",
                 f"{PUBLIC_URL}/parent")
    return {"ok": True, "request": r}


@app.post("/api/request/{rid}/cancel")
async def cancel_request(rid: str):
    async with state.lock:
        r = state.request(rid)
        if r["status"] == "pending":
            r["status"] = "cancelled"
            state.save()
    return {"ok": True}


# --------------------------------------------------------------- parent ----
@app.get("/api/parent/state")
async def parent_state(gt_parent: Optional[str] = Cookie(default=None)):
    require_parent(gt_parent)
    pols, err = await live_policies()
    t = now()
    try:
        version = await net.version()
    except Exception:
        version = None
    return {
        "now": iso(t), "mock": MOCK, "unifi_error": err, "version": version,
        "host": getattr(net, "host", None), "ntfy": bool(NTFY_URL), "max_minutes": MAX_MINUTES,
        "profiles": [profile_view(p, pols, t) | {"policy_ids": p["policy_ids"]} for p in state.d["profiles"]],
        "policies": sorted(pols.values(), key=lambda p: p.get("index") or 0),
        "requests": [r | {"profile": next((p["name"] for p in state.d["profiles"] if p["id"] == r["profile_id"]), "?")}
                     for r in reversed(state.d["requests"][-30:])],
        "log": list(reversed(state.d["log"][-60:])),
    }


@app.post("/api/parent/requests/{rid}/approve")
async def approve(rid: str, req: Request, gt_parent: Optional[str] = Cookie(default=None)):
    require_parent(gt_parent)
    body = await req.json() if int(req.headers.get("content-length") or 0) else {}
    async with state.lock:
        r = state.request(rid)
        if r["status"] != "pending":
            raise HTTPException(409, f"request is {r['status']}")
        p = state.profile(r["profile_id"])
        minutes = int(body.get("minutes") or r["minutes"])
        r["status"] = "approved"
        r["minutes"] = minutes
        until = await grant(p, minutes, "parent (approved)")
    return {"ok": True, "until": iso(until)}


@app.post("/api/parent/requests/{rid}/deny")
async def deny(rid: str, gt_parent: Optional[str] = Cookie(default=None)):
    require_parent(gt_parent)
    async with state.lock:
        r = state.request(rid)
        if r["status"] == "pending":
            r["status"] = "denied"
            state.note(f"{state.profile(r['profile_id'])['name']}: request denied")
            state.save()
    return {"ok": True}


@app.post("/api/parent/profiles/{pid}/grant")
async def grant_now(pid: str, req: Request, gt_parent: Optional[str] = Cookie(default=None)):
    require_parent(gt_parent)
    body = await req.json()
    async with state.lock:
        p = state.profile(pid)
        pend = state.pending_for(pid)
        if pend:
            pend["status"] = "approved"
        until = await grant(p, int(body.get("minutes", 30)), "parent")
    return {"ok": True, "until": iso(until)}


@app.post("/api/parent/profiles/{pid}/end")
async def end_now(pid: str, gt_parent: Optional[str] = Cookie(default=None)):
    require_parent(gt_parent)
    async with state.lock:
        await end(state.profile(pid), "ended by parent")
    return {"ok": True}


@app.post("/api/parent/profiles")
async def save_profile(req: Request, gt_parent: Optional[str] = Cookie(default=None)):
    require_parent(gt_parent)
    body = await req.json()
    name = str(body.get("name", "")).strip()[:40]
    ids = [str(x) for x in body.get("policy_ids", [])]
    if not name:
        raise HTTPException(400, "name required")
    async with state.lock:
        pid = body.get("id")
        if pid:
            p = state.profile(pid)
            p.update(name=name, policy_ids=ids, icon=str(body.get("icon") or p.get("icon") or "🎮")[:4],
                     max_minutes=int(body.get("max_minutes") or MAX_MINUTES))
        else:
            p = {"id": uuid.uuid4().hex[:8], "name": name, "policy_ids": ids, "icon": str(body.get("icon") or "🎮")[:4],
                 "max_minutes": int(body.get("max_minutes") or MAX_MINUTES)}
            state.d["profiles"].append(p)
        state.note(f"profile saved: {name} ({len(ids)} policies)")
        state.save()
    return {"ok": True, "profile": p}


@app.delete("/api/parent/profiles/{pid}")
async def delete_profile(pid: str, gt_parent: Optional[str] = Cookie(default=None)):
    require_parent(gt_parent)
    async with state.lock:
        p = state.profile(pid)
        if pid in state.d["grants"]:
            await end(p, "profile deleted")
        state.d["profiles"] = [x for x in state.d["profiles"] if x["id"] != pid]
        state.note(f"profile deleted: {p['name']}")
        state.save()
    return {"ok": True}


@app.post("/api/parent/policies/{policy_id}")
async def toggle_policy(policy_id: str, req: Request, gt_parent: Optional[str] = Cookie(default=None)):
    require_parent(gt_parent)
    body = await req.json()
    enabled = bool(body.get("enabled"))
    try:
        p = await net.set_enabled(policy_id, enabled)
    except unifi.UniFiError as e:
        raise HTTPException(502, str(e))
    async with state.lock:
        state.note(f"policy '{p['name']}' {'enabled' if enabled else 'disabled'} by parent")
        state.save()
    return {"ok": True, "policy": p}


# ---------------------------------------------------------------- pages ----
@app.exception_handler(HTTPException)
async def http_err(_, exc):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.get("/")
async def kid_page():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/parent")
async def parent_page():
    return FileResponse(os.path.join(HERE, "static", "parent.html"))


@app.get("/healthz")
async def healthz():
    return {"ok": True, "mock": MOCK}


app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
