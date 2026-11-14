"""Labels a profile reads from a file's own export: the people Google Takeout lists in a photo's sidecar, for instance.

filecat knows nothing about any service. A profile opts in with two things: a class attribute `label_exts` (lower-case
extensions, e.g. (".jpg", ".heic")) and a method `labels(rel_path) -> list[(kind, value)] | None` that looks for the
label source next to the file (`rel_path` is the stored path under the profile's root) and returns None when the export
has no label source for that file. Each current file row is looked at once (table `label_scans`); the labels go to
`file_labels` (kind, value) and are queried with plain SQL, e.g. the files that share a label with a visually
identical file (see `visual.py`).
"""

import time

from .core import coll, roots_of
from .profiles import load_profile


def label_profile(cl, label, path):
    cls = load_profile(cl["profile"])
    if not hasattr(cls, "labels") or not getattr(cls, "label_exts", None):
        return None
    return cls(cl["config"], path)


def pending_where(exts):
    ext = " OR ".join(f"LOWER(f.path) LIKE '%{e}'" for e in exts)
    return (
        f"f.collection_id=? AND f.root=? AND f.current=1 AND f.state='ok' AND ({ext}) AND NOT EXISTS "
        "(SELECT 1 FROM label_scans s WHERE s.file_id=f.id AND s.source=?)"
    )


def read_pending(c, seconds, only=None):
    """Label every pending file of the collections whose profile can label, until the time budget is spent (resumable)."""
    end = time.time() + seconds
    done = none = bad = nlab = 0
    names = [only] if only else [r[0] for r in c.execute("SELECT name FROM collections ORDER BY id").fetchall()]
    for name in names:
        cl = coll(c, name)
        for label, (path, _auto) in roots_of(c, cl["id"]).items():
            prof = label_profile(cl, label, path)
            if prof is None:
                continue
            exts = tuple(prof.label_exts)
            q = "SELECT f.id,f.path FROM files f WHERE " + pending_where(exts) + " AND f.id>? ORDER BY f.id LIMIT 500"
            last = 0
            while time.time() < end:
                rows = c.execute(q, (cl["id"], label, cl["profile"], last)).fetchall()
                c.commit()
                if not rows:
                    break
                last = rows[-1][0]
                for fid, rel in rows:
                    try:
                        found = prof.labels(rel)
                    except OSError:
                        found = None
                        state = "error"
                    except ValueError:  # a malformed label source: recorded once, not retried every slice
                        found = None
                        state = "error"
                    else:
                        state = "none" if found is None else "ok"
                    for kind, value in sorted(set(found or ())):
                        c.execute("INSERT INTO file_labels(file_id,kind,value) VALUES(?,?,?)", (fid, kind, value))
                        nlab += 1
                    c.execute(
                        "INSERT INTO label_scans(file_id,source,state) VALUES(?,?,?)", (fid, cl["profile"], state)
                    )
                    done += state == "ok"
                    none += state == "none"
                    bad += state == "error"
                c.commit()
    print(f"labels: {done} files labelled ({nlab} labels), {none} without a label source, {bad} unreadable")
    return done


def summary(c, cid):
    """[(kind, distinct values, labels)] of a collection's current files."""
    return c.execute(
        "SELECT l.kind,COUNT(DISTINCT l.value),COUNT(*) FROM file_labels l JOIN files f ON f.id=l.file_id "
        "WHERE f.collection_id=? AND f.current=1 GROUP BY l.kind ORDER BY l.kind",
        (cid,),
    ).fetchall()


def find(c, kind, value, collection=None, limit=20):
    """Paths of current files with the label (kind=value)."""
    where = "l.kind=? AND l.value=? AND f.current=1" + (
        " AND f.collection_id=%d" % coll(c, collection)["id"] if collection else ""
    )
    out = [
        f"{n}:{root}:{path}"
        for n, root, path in c.execute(
            "SELECT (SELECT name FROM collections WHERE id=f.collection_id),f.root,f.path FROM file_labels l "
            f"JOIN files f ON f.id=l.file_id WHERE {where} ORDER BY f.id LIMIT ?",
            (kind, value, limit),
        )
    ]
    for line in out:
        print(line)
    return out
