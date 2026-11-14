"""filecat command line."""

import argparse

from . import core, labels, report, visual
from .db import connect


def build_parser():
    ap = argparse.ArgumentParser(
        prog="filecat",
        description="One catalogue and SHA-256 index for many file collections (SQLite or PostgreSQL: FILECAT_DB).",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    col = sub.add_parser("collection", help="add or list collections").add_subparsers(dest="sub", required=True)
    x = col.add_parser("add")
    x.add_argument("name")
    x.add_argument("--profile", default="plain")
    x.add_argument("--root", action="append", help="LABEL=PATH[,autoscan]")
    x.add_argument("--set", action="append", help="key=value profile config")
    x.add_argument("--note")
    col.add_parser("list")
    x = sub.add_parser("scan", help="incremental walk of the roots")
    x.add_argument("name")
    x.add_argument("--root")
    x = sub.add_parser("ingest-archive", help="record an archive from its index, nothing is read or extracted")
    x.add_argument("name")
    x.add_argument("archive")
    x.add_argument("--root")
    x.add_argument("--strip", type=int)
    x.add_argument("--skip", action="append")
    x = sub.add_parser("hash", help="SHA-256 files that have none yet")
    x.add_argument("--seconds", type=int, default=1500)
    x.add_argument("--collection")
    x.add_argument("--stop-when", help='shell command; hashing stops while it succeeds (e.g. "pgrep -f bsdtar")')
    x = sub.add_parser("visual-hash", help="perceptual hash (pHash) of image files that have none yet")
    x.add_argument("--seconds", type=int, default=1500)
    x.add_argument("--collection")
    x.add_argument("--workers", type=int, default=2, help="decoding processes (default 2, niced; 1 = in-process)")
    x = sub.add_parser("similar", help="byte-different images that look the same (pHash distance)")
    x.add_argument("--distance", type=int, default=6, help="max Hamming distance of 64 bits")
    x.add_argument("--across", action="store_true", help="only groups spanning more than one collection")
    x.add_argument("--limit", type=int, default=20)
    x.add_argument("--collection")
    x = sub.add_parser("labels", help="read labels (e.g. people) a profile finds next to files; each file once")
    x.add_argument("--seconds", type=int, default=1500)
    x.add_argument("--collection")
    x.add_argument("--find", metavar="KIND=VALUE", help="list the files with a label instead of reading")
    x.add_argument("--limit", type=int, default=20)
    x = sub.add_parser("run", help="profile ingest + autoscan roots + hash (for a timer)")
    x.add_argument("--seconds", type=int, default=1500)
    x.add_argument("--workers", type=int, default=2, help="visual-hash decoding processes")
    x.add_argument("--stop-when", help="shell command; hashing stops while it succeeds")
    x = sub.add_parser("report")
    x.add_argument("name", nargs="?")
    x = sub.add_parser("dups", help="biggest sets of identical files")
    x.add_argument("--across", action="store_true", help="only contents present in more than one collection")
    x.add_argument("--min-size", type=int, default=1000000)
    x.add_argument("--limit", type=int, default=20)
    x.add_argument("--collection")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    c = connect()
    if a.cmd == "collection":
        if a.sub == "add":
            core.add_collection(
                c, a.name, a.profile, a.root or [], dict(kv.split("=", 1) for kv in a.set or []), a.note
            )
            print(f"collection {a.name} added")
        else:
            report.collections(c)
    elif a.cmd == "scan":
        cl = core.coll(c, a.name)
        for l, (p, _) in core.roots_of(c, cl["id"]).items():
            if a.root in (None, l):
                core.scan_root(c, cl, l, p)
    elif a.cmd == "ingest-archive":
        core.ingest_archive(c, core.coll(c, a.name), a.archive, a.root, a.strip, a.skip)
    elif a.cmd == "hash":
        core.hash_pending(c, a.seconds, a.collection, a.stop_when)
    elif a.cmd == "visual-hash":
        visual.hash_pending(c, a.seconds, a.collection, workers=a.workers)
    elif a.cmd == "similar":
        visual.similar(c, a.distance, a.across, a.limit, a.collection)
    elif a.cmd == "labels":
        if a.find:
            kind, _, value = a.find.partition("=")
            labels.find(c, kind, value, a.collection, a.limit)
        else:
            labels.read_pending(c, a.seconds, a.collection)
    elif a.cmd == "run":
        core.run_all(c, a.seconds, a.stop_when, a.workers)
    elif a.cmd == "report":
        report.report(c, a.name)
    elif a.cmd == "dups":
        report.dups(c, a.min_size, a.limit, a.across, a.collection)
