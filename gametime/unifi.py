"""UniFi Network client: list the things that can block a device and flip
their `enabled` flag. Two sources, both authenticated with the same console
API key (header X-API-KEY), both read-modify-write:

  * Firewall policies (zone-based firewall) — the official Integration API,
    https://<gateway>/proxy/network/integration/v1/...  (Network 10.1+).
    PATCH only takes loggingEnabled, so: GET -> drop read-only fields -> PUT.
    Skipped when the gateway says the zone-based firewall isn't configured.
  * Traffic rules (Settings -> Policy Engine / Traffic Management, the older
    per-device "block internet on a schedule" rules) — the console's own
    https://<gateway>/proxy/network/v2/api/site/<site>/trafficrules, which
    accepts the same key. PUT the whole rule back with `enabled` flipped.

Items carry `kind` ("policy" | "traffic_rule"); ids are UUIDs for policies and
24-hex Mongo ids for traffic rules, so set_enabled can tell them apart.

UNIFI_MOCK=1 swaps in an in-memory fake with a few policies, for demos and
for running the app without a gateway.
"""
import asyncio
import os
import ssl
import uuid

import httpx



class UniFiError(Exception):
    pass


class UniFi:
    def __init__(self, host, api_key, site="default"):
        self.host = host.rstrip("/")
        self.site_ref = site
        self._site_id = None
        self._lock = asyncio.Lock()
        # Gateways serve a self-signed / console-local cert; the API key is the trust anchor.
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        self._c = httpx.AsyncClient(
            base_url=f"{self.host}/proxy/network",
            headers={"X-API-KEY": api_key, "Accept": "application/json"},
            verify=ctx, timeout=15,
        )
        self.zbf = None   # None = unknown, False = zone-based firewall not configured

    async def _req(self, method, path, **kw):
        """path under /proxy/network: '/integration/v1/...' or '/v2/api/...'."""
        try:
            r = await self._c.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise UniFiError(f"UniFi unreachable: {e}") from e
        if r.status_code >= 400:
            body = r.text[:300]
            if r.status_code == 401:
                body = "API key rejected (create one in the console: Settings -> Control Plane -> Integrations)"
            raise UniFiError(f"UniFi {method} {path} -> {r.status_code}: {body}")
        return r.json() if r.content else None

    async def version(self):
        return (await self._req("GET", "/integration/v1/info"))["applicationVersion"]

    async def site_id(self):
        if self._site_id:
            return self._site_id
        async with self._lock:
            if self._site_id:
                return self._site_id
            page = await self._req("GET", "/integration/v1/sites", params={"limit": 200})
            sites = page.get("data", [])
            for s in sites:
                if s.get("internalReference") == self.site_ref or s.get("name") == self.site_ref:
                    self._site_id = s["id"]
                    return self._site_id
            if len(sites) == 1:
                self._site_id = sites[0]["id"]
                return self._site_id
            raise UniFiError(f"site '{self.site_ref}' not found; sites: {[s.get('internalReference') for s in sites]}")

    async def list_policies(self):
        return await self._firewall_policies() + await self._traffic_rules()

    async def set_enabled(self, item_id, enabled):
        try:
            return await self._set_policy(item_id, enabled)
        except UniFiError as e:
            if "-> 404" not in str(e):
                raise
        return await self._set_traffic_rule(item_id, enabled)

    # -- zone-based firewall policies (console v2 API) --
    # The official Integration API omits `id` on policies migrated from traffic
    # rules (seen on 10.6.106), so the console's own endpoint is used instead:
    # it always has `_id`, takes the same key, and PUT of the full object works.
    async def _firewall_policies(self):
        try:
            pols = await self._req("GET", f"/v2/api/site/{self.site_ref}/firewall-policies")
        except UniFiError as e:
            if "-> 404" in str(e) or "not-configured" in str(e):
                return []
            raise
        mine = [p for p in (pols or []) if not p.get("predefined")]
        mine.sort(key=lambda p: p.get("index", 0))
        return [policy_summary(p) for p in mine]

    async def _set_policy(self, policy_id, enabled):
        path = f"/v2/api/site/{self.site_ref}/firewall-policies/{policy_id}"
        full = await self._req("GET", path)
        if bool(full.get("enabled")) == bool(enabled):
            return policy_summary(full)
        body = dict(full)
        body["enabled"] = bool(enabled)
        updated = await self._req("PUT", path, json=body)
        if bool((updated or {}).get("enabled")) != bool(enabled):
            raise UniFiError(f"policy {policy_id} did not take enabled={enabled}")
        return policy_summary(updated)

    # -- traffic rules (console v2 API) --
    async def _traffic_rules(self):
        try:
            rules = await self._req("GET", f"/v2/api/site/{self.site_ref}/trafficrules")
        except UniFiError as e:
            if "-> 404" in str(e):
                return []
            raise
        return [rule_summary(r, i) for i, r in enumerate(rules or [])]

    async def _set_traffic_rule(self, rule_id, enabled):
        rules = await self._req("GET", f"/v2/api/site/{self.site_ref}/trafficrules") or []
        rule = next((r for r in rules if r.get("_id") == rule_id), None)
        if rule is None:
            raise UniFiError(f"traffic rule {rule_id} not found")
        if bool(rule.get("enabled")) == bool(enabled):
            return rule_summary(rule, 0)
        body = dict(rule)
        body["enabled"] = bool(enabled)
        updated = await self._req("PUT", f"/v2/api/site/{self.site_ref}/trafficrules/{rule_id}", json=body)
        if bool((updated or {}).get("enabled")) != bool(enabled):
            raise UniFiError(f"traffic rule {rule_id} did not take enabled={enabled}")
        return rule_summary(updated, 0)

    async def close(self):
        await self._c.aclose()


def summary(p):
    """Firewall policy as returned by the Integration API (kept for reference/tests)."""
    src = (p.get("source") or {}).get("trafficFilter") or {}
    dst = (p.get("destination") or {}).get("trafficFilter") or {}
    return {
        "id": p["id"],
        "name": p.get("name", "?"),
        "description": p.get("description") or "",
        "enabled": bool(p.get("enabled")),
        "action": (p.get("action") or {}).get("type", "?"),
        "index": p.get("index"),
        "source": _filter_label(src),
        "destination": _filter_label(dst),
        "schedule": "",
        "sched": None,
        "kind": "policy",
    }


def policy_summary(p):
    """Firewall policy as returned by the console v2 API."""
    def side(x):
        x = x or {}
        if x.get("client_macs"):
            n = len(x["client_macs"]); return f"{n} device{'s' if n != 1 else ''}"
        if x.get("ips"):
            return "ip: " + ", ".join(x["ips"][:3])
        if x.get("network_ids"):
            return f"{len(x['network_ids'])} networks"
        if x.get("app_ids") or x.get("app_category_ids"):
            return f"{len(x.get('app_ids') or [])} apps / {len(x.get('app_category_ids') or [])} categories"
        if x.get("domains"):
            return "domains: " + ", ".join(d.get("domain", str(d)) if isinstance(d, dict) else str(d) for d in x["domains"][:3])
        if x.get("regions"):
            return f"{len(x['regions'])} regions"
        # zone-only side (no console endpoint exposes zone names to the API key)
        return "any" if x.get("matching_target", "ANY") == "ANY" else (x.get("matching_target") or "?").lower()
    return {
        "id": p["_id"],
        "name": (p.get("name") or "(unnamed policy)").strip(),
        "description": p.get("description") or "",
        "enabled": bool(p.get("enabled")),
        "action": p.get("action", "?"),
        "index": p.get("index", 0),
        "source": side(p.get("source")),
        "destination": side(p.get("destination")),
        "schedule": schedule_label(p.get("schedule") or {}),
        "sched": normalize_schedule(p.get("schedule") or {}),
        "kind": "policy",
    }


DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def rule_summary(r, i):
    """The few fields the UI shows (traffic rule)."""
    devs = r.get("target_devices") or []
    what = []
    if r.get("app_ids"):
        what.append(f"{len(r['app_ids'])} apps")
    if r.get("app_category_ids"):
        what.append(f"{len(r['app_category_ids'])} app categories")
    if r.get("domains"):
        what.append(", ".join(d.get("domain", str(d)) if isinstance(d, dict) else str(d) for d in r["domains"][:3]))
    if r.get("regions"):
        what.append(f"{len(r['regions'])} regions")
    target = (r.get("matching_target") or "?").lower()
    return {
        "id": r["_id"],
        "name": (r.get("description") or "(unnamed rule)").strip(),
        "description": "",
        "enabled": bool(r.get("enabled")),
        "action": r.get("action", "?"),
        "index": 1000 + i,
        "source": f"{len(devs)} device{'s' if len(devs) != 1 else ''}" if devs
                  else (f"{len(r['network_ids'])} networks" if r.get("network_ids") else "everyone"),
        "destination": target + (": " + ", ".join(what) if what else ""),
        "schedule": schedule_label(r.get("schedule") or {}),
        "sched": normalize_schedule(r.get("schedule") or {}),
        "kind": "traffic_rule",
    }


def normalize_schedule(sc):
    """One shape for the console's two spellings (snake_case rules, camelCase API):
    {"mode", "days": [mon..sun], "start": "HH:MM", "end": "HH:MM", "all_day",
     "date_start", "date_end"}. mode ALWAYS -> None (no schedule)."""
    mode = sc.get("mode", "ALWAYS")
    if mode == "ALWAYS":
        return None
    raw = [str(x)[:3].lower() for x in (sc.get("repeat_on_days") or sc.get("repeatOnDays") or [])]
    days = [d for d in DAYS if d in raw]
    if mode == "EVERY_DAY" or (mode == "EVERY_WEEK" and not days):
        days = list(DAYS)
    tf = sc.get("timeFilter") or {}
    return {
        "mode": mode, "days": days,
        "start": sc.get("time_range_start") or tf.get("startTime") or "00:00",
        "end": sc.get("time_range_end") or tf.get("stopTime") or "00:00",
        "all_day": bool(sc.get("time_all_day", sc.get("allDay", False))),
        "date_start": sc.get("date_start") or sc.get("startDate"),
        "date_end": sc.get("date_end") or sc.get("stopDate"),
    }


def schedule_label(sc):
    n = normalize_schedule(sc)
    if n is None:
        return "always"
    days = n["days"]
    if len(days) == 7:
        when = "every day"
    elif days == DAYS[:5]:
        when = "weekdays"
    elif days == DAYS[5:]:
        when = "weekends"
    else:
        when = ", ".join(d.capitalize() for d in days) or n["mode"].lower()
    time = "all day" if n["all_day"] else f"{n['start']}–{n['end']}"
    if n["date_start"]:
        when += f" ({n['date_start']} → {n['date_end'] or '…'})"
    return f"{when} {time}"


def _hm(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def _date_ok(n, day):
    return (not n["date_start"] or str(day) >= n["date_start"]) and (not n["date_end"] or str(day) <= n["date_end"])


def windows(n, day):
    """Active windows of a schedule on local date `day` (previous-day windows
    that cross midnight included), as (start_dt, end_dt) naive local datetimes."""
    import datetime as dt
    out = []
    for d in (day - dt.timedelta(days=1), day):
        if DAYS[d.weekday()] not in n["days"] or not _date_ok(n, d):
            continue
        base = dt.datetime.combine(d, dt.time())
        if n["all_day"]:
            s, e = 0, 24 * 60
        else:
            s, e = _hm(n["start"]), _hm(n["end"])
            if e <= s:
                e += 24 * 60          # crosses midnight
        out.append((base + dt.timedelta(minutes=s), base + dt.timedelta(minutes=e)))
    return out


def active_at(n, t):
    """Is the (normalized) schedule active at naive local datetime t?"""
    if n is None:
        return True
    return any(s <= t < e for s, e in windows(n, t.date()))


def blocking_now(item, t):
    return bool(item.get("enabled")) and active_at(item.get("sched"), t)


def next_window(items, t, horizon_days=8):
    """Earliest upcoming (start, end) among enabled scheduled items after t."""
    import datetime as dt
    best = None
    for it in items:
        n = it.get("sched")
        if not it.get("enabled") or n is None:
            continue
        for i in range(horizon_days):
            for s, e in windows(n, t.date() + dt.timedelta(days=i)):
                if s > t and (best is None or s < best[0]):
                    best = (s, e)
    return best


def blocked_until(items, t, cap_hours=48):
    """If blocked at t, when does it end (chaining back-to-back windows)?"""
    import datetime as dt
    cur, limit = t, t + dt.timedelta(hours=cap_hours)
    moved = True
    while moved and cur < limit:
        moved = False
        for it in items:
            n = it.get("sched")
            if not it.get("enabled"):
                continue
            if n is None:
                return None            # unscheduled blocker: blocked indefinitely
            for s, e in windows(n, cur.date()):
                if s <= cur < e and e > cur:
                    cur, moved = e, True
    return cur


class MockUniFi:
    """Same surface as UniFi, no gateway. Policies live in memory."""

    def __init__(self):
        self._policies = {}
        demo = [
            ("Block Gaming PC — internet", "BLOCK", "mac address: aa:bb:cc:dd:ee:01", "Zone: External"),
            ("Block Gaming PC — Steam & Discord", "BLOCK", "mac address: aa:bb:cc:dd:ee:01", "application: Steam, Discord"),
            ("Block Xbox — internet", "BLOCK", "mac address: aa:bb:cc:dd:ee:02", "Zone: External"),
            ("Block IoT -> Private", "BLOCK", "network: IoT", "network: Private"),
        ]
        for i, (name, action, src, dst) in enumerate(demo):
            pid = str(uuid.uuid5(uuid.NAMESPACE_URL, name))
            self._policies[pid] = {"id": pid, "name": name, "description": "demo policy", "enabled": True,
                                   "action": action, "index": i, "source": src, "destination": dst,
                                   "schedule": "", "sched": None, "kind": "policy"}
        rid = "6a0000000000000000000001"
        self._policies[rid] = {"id": rid, "name": "Gaming PC - Weeknights", "description": "", "enabled": True,
                               "action": "BLOCK", "index": 1000, "source": "1 device", "destination": "internet",
                               "schedule": "Sun, Mon, Tue, Wed, Thu 21:30–01:00", "kind": "traffic_rule",
                               "sched": {"mode": "EVERY_WEEK", "days": ["mon", "tue", "wed", "thu", "sun"], "start": "21:30",
                                         "end": "01:00", "all_day": False, "date_start": None, "date_end": None}}

    async def version(self):
        return "mock"

    async def list_policies(self):
        return [dict(p) for p in sorted(self._policies.values(), key=lambda p: p["index"])]

    async def set_enabled(self, policy_id, enabled):
        if policy_id not in self._policies:
            raise UniFiError(f"no such policy {policy_id}")
        self._policies[policy_id]["enabled"] = bool(enabled)
        return dict(self._policies[policy_id])

    async def close(self):
        pass


def from_env():
    if os.environ.get("UNIFI_MOCK") == "1":
        return MockUniFi()
    key = os.environ.get("UNIFI_API_KEY")
    if not key:
        raise SystemExit("UNIFI_API_KEY is not set (run setup.sh), or set UNIFI_MOCK=1 for a demo")
    return UniFi(os.environ.get("UNIFI_HOST", "https://192.168.0.1"), key,
                 os.environ.get("UNIFI_SITE", "default"))
