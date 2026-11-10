"""build_static.py - produce the GitHub Pages site in docs/.

Run by .github/workflows/feed.yml on a cron (and locally: python webapp/build_static.py).
Steps: download current-season results + fixtures odds + season schedule, refit ratings,
compute upcoming and last-round views, write JSON + copy the static page.

Output (docs/):
  index.html, styles3d.css, static/app.css, static/app.js
  data/meta.json       build time, feed status
  data/ratings.json    fitted ratings per league (the browser computes forecasts from this)
  data/backtest.json   Page 1 summary from backtest/out/predictions.csv
  data/upcoming.json   next fixtures with model probabilities and market odds
  data/recent.json     last round, model vs result
--offline skips every download and builds from the cached files only.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import analytics   # noqa: E402
import live        # noqa: E402
import ratings     # noqa: E402
import views       # noqa: E402

STATIC_FLAG = "<script>window.APEX_STATIC = true;</script>"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "docs"))
    ap.add_argument("--data", default=os.path.join(ROOT, "data"))
    ap.add_argument("--cache", default=os.path.join(HERE, "cache"))
    ap.add_argument("--pred", default=os.path.join(ROOT, "backtest", "out", "predictions.csv"))
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    t0 = time.time()

    cache_path = os.path.join(args.cache, "ratings.json")
    state = {}

    def refit():
        state["cache"] = ratings.build_cache(args.data)
        ratings.save(state["cache"], cache_path)

    feed = live.LiveFeed(args.data, args.cache, refit, interval_hours=6)
    if not args.offline:
        r = feed.refresh()
        print("refresh:", "ok" if r["ok"] else r.get("error"))
    if "cache" not in state:
        state["cache"] = ratings.load_or_build(cache_path, args.data)
    cache = state["cache"]

    out = args.out
    os.makedirs(os.path.join(out, "data"), exist_ok=True)
    os.makedirs(os.path.join(out, "static"), exist_ok=True)

    def dump(name, obj):
        with open(os.path.join(out, "data", name), "w", encoding="utf-8") as fh:
            json.dump(obj, fh, separators=(",", ":"))

    upcoming = views.upcoming_view(cache, feed.upcoming())
    recent = views.recent_view(cache, feed.recent())
    backtest = analytics.build_summary(args.pred) if os.path.exists(args.pred) else None
    built = datetime.now(timezone.utc).isoformat(timespec="seconds")

    dump("ratings.json", cache)
    dump("upcoming.json", {"fixtures": upcoming, "note": views.GATE_NOTE, "fitted_at": cache["fitted_at"],
                           "built_at": built})
    dump("recent.json", recent)
    if backtest:
        dump("backtest.json", backtest)
    status = dict(feed.status)
    status.update({"built_at": built, "auto_refresh": True, "mode": "github-pages",
                   "fixtures_cached": len(feed.fixtures), "schedule_cached": len(feed.schedule),
                   "upcoming": len(upcoming),
                   "data_to": {k: v["last_match_date"] for k, v in cache["leagues"].items()}})
    dump("meta.json", status)

    # static page: same files as the server, plus the static-mode flag
    with open(os.path.join(HERE, "static", "index.html"), encoding="utf-8") as fh:
        html = fh.read().replace("<head>", "<head>\n" + STATIC_FLAG, 1)
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(html)
    shutil.copy(os.path.join(ROOT, "styles3d.css"), os.path.join(out, "styles3d.css"))
    for f in ("app.css", "app.js"):
        shutil.copy(os.path.join(HERE, "static", f), os.path.join(out, "static", f))
    with open(os.path.join(out, ".nojekyll"), "w") as fh:
        fh.write("")
    print(f"built {out} in {time.time() - t0:.1f}s: {len(upcoming)} upcoming, {recent['n']} recent, "
          f"backtest {'yes' if backtest else 'no'}")


if __name__ == "__main__":
    main()
