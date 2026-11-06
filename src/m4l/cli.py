"""Local development entry point. No AWS credentials needed for anything here.

    python -m m4l.cli fetch 2026-08-06            # fetch + parse one date, print it (saves nothing)
    python -m m4l.cli parse page.html 2026-08-06  # parse a saved HTML file
    python -m m4l.cli scrape                      # incremental scrape into ./data, then build ./public
    python -m m4l.cli scrape --date 2026-08-06    # refresh one specific drawing
    python -m m4l.cli scrape --full               # re-fetch every drawing since launch
    python -m m4l.cli build                       # regenerate ./public from ./data (no network)
    python -m m4l.cli stats                       # print computed statistics as JSON
    python -m m4l.cli check 2026-08-06 7 20 42 48 51 3
    python -m m4l.cli serve                       # preview ./public at http://localhost:8000

(Run with PYTHONPATH=src, or use the ./dev.sh wrapper.)
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from . import dataset as ds
from .pipeline import RunOptions, publish, run
from .storage import LocalStorage

ROOT = Path(__file__).resolve().parents[2]


def main(argv=None):
    p = argparse.ArgumentParser(prog="m4l")
    p.add_argument("--data-dir", default=str(ROOT / "data"))
    p.add_argument("--out-dir", default=str(ROOT / "public"))
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch"); f.add_argument("date")
    pa = sub.add_parser("parse"); pa.add_argument("file"); pa.add_argument("date")
    s = sub.add_parser("scrape")
    s.add_argument("--full", action="store_true")
    s.add_argument("--date", action="append")
    s.add_argument("--max", type=int)
    s.add_argument("--no-publish", action="store_true")
    s.add_argument("--no-snapshots", action="store_true")
    sub.add_parser("build")
    sub.add_parser("stats")
    c = sub.add_parser("check"); c.add_argument("date"); c.add_argument("numbers", nargs=6, type=int)
    sv = sub.add_parser("serve"); sv.add_argument("--port", type=int, default=8000)

    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    state, site = LocalStorage(a.data_dir), LocalStorage(a.out_dir)

    if a.cmd == "fetch":
        from .scraper import Fetcher
        r = Fetcher().fetch_date(a.date)
        print(json.dumps(r.record if r.ok else {"failure": r.failure_kind, "detail": r.detail}, indent=1))
        return 0 if r.ok else 1

    if a.cmd == "parse":
        from .parser import ParseError, parse_draw_page
        try:
            print(json.dumps(parse_draw_page(Path(a.file).read_text(), a.date, "local"), indent=1))
        except ParseError as e:
            print(f"{e.kind}: {e.detail}", file=sys.stderr)
            return 1
        return 0

    if a.cmd == "scrape":
        out = run(state, site, RunOptions(full_refresh=a.full, dates=a.date, max_fetches=a.max,
                                          publish=not a.no_publish, snapshots=not a.no_snapshots))
        print(json.dumps(out, indent=1))
        return 1 if out["alarms"] else 0

    data = ds.load_json(state, ds.DATASET_KEY, ds.empty_dataset())

    if a.cmd == "build":
        print(json.dumps(publish(state, site, data, force=True), indent=1))
        return 0

    if a.cmd == "stats":
        from .stats import compute_stats
        print(json.dumps(compute_stats(ds.verified_drawings(data)), indent=1))
        return 0

    if a.cmd == "check":
        from .ticket_checker import check_ticket
        print(json.dumps(check_ticket(ds.verified_drawings(data), a.date,
                                      a.numbers[:5], a.numbers[5]), indent=1))
        return 0

    if a.cmd == "serve":
        import functools
        import http.server
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=a.out_dir)
        print(f"Serving {a.out_dir} at http://localhost:{a.port}/")
        http.server.ThreadingHTTPServer(("127.0.0.1", a.port), handler).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
