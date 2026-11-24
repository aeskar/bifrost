"""Single-seat MCP endpoint for handing issue references to a native coding client."""
import argparse
import json
import os
import re
import sqlite3
import sys
import time

PROVIDERS = ("codex", "claude")
IDENTITY = re.compile(r"[a-zA-Z0-9_.-]{1,64}")
REFERENCE = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/(issues|pull)/[1-9]\d*")
PROVIDER = {"type": "string", "enum": list(PROVIDERS)}
ISSUE = {"type": "string", "description": "GitHub issue or pull request URL"}
TOOLS = {
    "status": ("Show recent usage windows and open or claimed issue references for this seat.", {}),
    "publish_usage": ("Record the current subscription windows from the owner's native client.", {
        "provider": PROVIDER, "windows": {"type": "array", "maxItems": 2, "items": {"type": "object",
        "properties": {"minutes": {"type": "integer"}, "used_percent": {"type": "number"},
                       "reset_at": {"type": "integer"}},
        "required": ["minutes", "used_percent", "reset_at"], "additionalProperties": False}}}),
    "offer": ("Offer a coding issue for this seat to take in its native client.", {"reference": ISSUE, "provider": PROVIDER}),
    "claim": ("Accept an offered issue after the owner chooses to take it.", {"reference": ISSUE}),
    "finish": ("Mark a claimed issue complete.", {"reference": ISSUE}),
    "release": ("Return a claimed issue to the available queue.", {"reference": ISSUE}),
    "withdraw": ("Withdraw an offered issue.", {"reference": ISSUE}),
}


def execute(db, seat, tool, args):
    required = TOOLS[tool][1]
    if not isinstance(args, dict) or set(args) != set(required):
        raise ValueError("Incorrect tool arguments")
    provider = args.get("provider")
    if "provider" in args and provider not in PROVIDERS:
        raise ValueError("Unknown subscription provider")
    ref = args.get("reference")
    if "reference" in args and (not isinstance(ref, str) or not REFERENCE.fullmatch(ref) or len(ref) > 256):
        raise ValueError("Expected a GitHub issue or pull request URL")
    now = int(time.time())
    if tool == "status":
        windows = []
        for p, stamp, raw in db.execute("SELECT provider,stamp,windows FROM quota WHERE seat=?", (seat,)):
            windows.append(dict(provider=p, observed_at=stamp, fresh=0 <= now-stamp < 900,
                                windows=[w for w in json.loads(raw) if w["reset_at"] > now]))
        jobs = db.execute("SELECT ref,provider,state FROM jobs WHERE seat=? AND state IN ('offered','claimed') ORDER BY ref", (seat,))
        return dict(usage=windows, jobs=[dict(reference=r, provider=p, state=s) for r,p,s in jobs])
    if tool == "publish_usage":
        windows = args["windows"]
        if not isinstance(windows, list) or len(windows) > 2:
            raise ValueError("Expected up to two windows")
        seen = set()
        for w in windows:
            if (not isinstance(w, dict) or set(w) != {"minutes","used_percent","reset_at"}
                    or type(w["minutes"]) is not int or not 1 <= w["minutes"] <= 44640
                    or w["minutes"] in seen or type(w["used_percent"]) not in (int,float)
                    or not 0 <= w["used_percent"] <= 100 or type(w["reset_at"]) is not int
                    or not now < w["reset_at"] <= now+32*86400):
                raise ValueError("Invalid usage window")
            seen.add(w["minutes"])
        db.execute("INSERT OR REPLACE INTO quota VALUES(?,?,?,?)", (seat, provider, now, json.dumps(windows)))
        return {"accepted": len(windows)}
    if tool == "offer":
        db.execute("INSERT OR IGNORE INTO jobs VALUES(?,?,?,'offered')", (seat,ref,provider))
        p,state = db.execute("SELECT provider,state FROM jobs WHERE seat=? AND ref=?", (seat,ref)).fetchone()
        if p != provider:
            raise ValueError("This issue already has a provider")
        return {"state": state}
    before, after = {"claim": ("offered","claimed"), "finish": ("claimed","done"),
                     "release": ("claimed","offered"), "withdraw": ("offered","withdrawn")}[tool]
    changed = db.execute("UPDATE jobs SET state=? WHERE seat=? AND ref=? AND state=?", (after,seat,ref,before))
    if not changed.rowcount:
        row = db.execute("SELECT state FROM jobs WHERE seat=? AND ref=?", (seat,ref)).fetchone()
        if not row or row[0] != after:
            raise ValueError("Issue is missing or its state changed")
    return {"state": after}


def serve(db, seat, req):
    method = req.get("method")
    if method == "initialize":
        version = req.get("params", {}).get("protocolVersion")
        return {"protocolVersion": version if version in ("2024-11-05","2025-03-26","2025-06-18","2025-11-25") else "2025-06-18",
                "capabilities": {"tools": {}}, "serverInfo": {"name": "team-overflow", "version": "0.1.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [{"name": n, "description": desc, "inputSchema": {"type":"object","properties":props,
                          "required":list(props),"additionalProperties":False}} for n,(desc,props) in TOOLS.items()]}
    if method != "tools/call":
        raise KeyError("Unknown method")
    params = req.get("params", {})
    try:
        with db:
            result = execute(db, seat, params["name"], params.get("arguments", {}))
        return {"content": [{"type": "text", "text": json.dumps(result)}]}
    except (KeyError, TypeError, ValueError, sqlite3.OperationalError) as exc:
        return {"isError": True, "content": [{"type": "text", "text": str(exc)}]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seat", required=True)
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    if not IDENTITY.fullmatch(args.seat):
        parser.error("Invalid seat")
    os.umask(0o077)
    db = sqlite3.connect(args.database, timeout=5)
    db.executescript("CREATE TABLE IF NOT EXISTS jobs(seat TEXT,ref TEXT,provider TEXT,state TEXT,PRIMARY KEY(seat,ref));"
                     "CREATE TABLE IF NOT EXISTS quota(seat TEXT,provider TEXT,stamp INTEGER,windows TEXT,PRIMARY KEY(seat,provider));")
    for line in sys.stdin:
        request_id = None
        try:
            req = json.loads(line)
            if not isinstance(req, dict):
                raise ValueError("Invalid request")
            if "id" not in req:
                continue
            request_id = req["id"]
            response = {"result": serve(db, args.seat, req)}
        except (ValueError, KeyError, TypeError, AttributeError):
            response = {"error": {"code": -32601, "message": "Invalid request or unknown method"}}
        print(json.dumps({"jsonrpc":"2.0", "id":request_id, **response}), flush=True)


if __name__ == "__main__":
    main()
