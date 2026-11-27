"""Roxy — free, direct Instagram Reels publisher (official Instagram API with Instagram Login).

Runs from GitHub Actions on a schedule. Reads queue/instagram.json, publishes at most ONE due Reel
per run (and never two within 20 hours), marks it done, and the workflow commits the queue back.

Secrets (set by the account owner in GitHub > Settings > Secrets and variables > Actions):
  IG_TOKEN  — long-lived Instagram user access token for @roxy.why (valid ~60 days, refreshed here).
"""
import json, os, sys, time, datetime as dt, urllib.parse, urllib.request

API = "https://graph.instagram.com/v21.0"
REPO = os.environ.get("GITHUB_REPOSITORY", "kg2c86mfpy-design/Roxy")
SHA = os.environ.get("GITHUB_SHA", "main")
QUEUE = "queue/instagram.json"
MIN_GAP_H = 20


def call(method, url, params):
    data = urllib.parse.urlencode(params).encode()
    if method == "GET":
        req = urllib.request.Request(url + "?" + data.decode())
    else:
        req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise SystemExit(f"Instagram API error {e.code} on {url.split('?')[0]}: {body[:400]}")


def main():
    token = os.environ.get("IG_TOKEN", "").strip()
    if not token:
        print("IG_TOKEN secret is not set yet — nothing to do."); return
    now = dt.datetime.now(dt.timezone.utc)
    q = json.load(open(QUEUE))

    # keep the token alive (allowed once it is >24 h old; harmless otherwise)
    try:
        call("GET", "https://graph.instagram.com/refresh_access_token",
             {"grant_type": "ig_refresh_token", "access_token": token})
    except SystemExit as e:
        print("token refresh skipped:", e)

    done = [dt.datetime.fromisoformat(x["published_at"]) for x in q if x.get("published_at")]
    if done and (now - max(done)).total_seconds() < MIN_GAP_H * 3600:
        print("Last Reel went out less than", MIN_GAP_H, "h ago — waiting."); return

    due = [x for x in q if x["status"] == "queued" and dt.datetime.fromisoformat(x["publish_at"]) <= now]
    if not due:
        print("Nothing due."); return
    item = sorted(due, key=lambda x: x["publish_at"])[0]

    me = call("GET", f"{API}/me", {"fields": "user_id,username", "access_token": token})
    uid = me.get("user_id") or me.get("id")
    print("Publishing", item["id"], "to @" + me.get("username", "?"))

    video_url = f"https://raw.githubusercontent.com/{REPO}/{SHA}/{item['video']}"
    c = call("POST", f"{API}/{uid}/media", {"media_type": "REELS", "video_url": video_url,
                                             "caption": item["caption"], "share_to_feed": "true",
                                             "access_token": token})
    cid = c["id"]
    for _ in range(60):  # up to ~10 min for Instagram to process the video
        s = call("GET", f"{API}/{cid}", {"fields": "status_code,status", "access_token": token})
        if s.get("status_code") == "FINISHED": break
        if s.get("status_code") in ("ERROR", "EXPIRED"):
            item["status"] = "error"; item["error"] = s.get("status", "")
            json.dump(q, open(QUEUE, "w"), ensure_ascii=False, indent=1)
            raise SystemExit(f"Instagram could not process the video: {s}")
        time.sleep(10)
    else:
        raise SystemExit("Video still processing after 10 min — will retry next run.")

    p = call("POST", f"{API}/{uid}/media_publish", {"creation_id": cid, "access_token": token})
    link = call("GET", f"{API}/{p['id']}", {"fields": "permalink", "access_token": token}).get("permalink", "")
    item.update(status="published", published_at=now.isoformat(), media_id=p["id"], permalink=link)
    json.dump(q, open(QUEUE, "w"), ensure_ascii=False, indent=1)
    print("Published:", link)


if __name__ == "__main__":
    main()
