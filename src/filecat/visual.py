"""Perceptual hashes of image files, to find the same picture across different files (resized, recompressed, another
format) and visually similar ones.

pHash, 64 bits: greyscale, 32x32, DCT, keep the 8x8 lowest frequencies, one bit per coefficient (above/below the median
of all but the DC term). Pure Python (the DCT is separable and only 8 of 32 outputs are needed: ~10k multiplications),
so the only dependency is Pillow, plus pillow-heif for HEIC/AVIF; both come with the `visual` extra. Distances are
Hamming distances; <= 6 of 64 is the usual "same picture" threshold. The pHash is stable under resizing, recompression
and format changes, mild edits and colour changes; it is NOT stable under crops or rotations (EXIF orientation is applied
first, so a phone photo and its upright copy match).

First frame only for animated GIF/WebP. Camera RAW and video are not covered here (see docs/progress.md).
"""

import math
import os
import sys
import time

ALGO = "phash64"
# Extensions Pillow opens natively, plus HEIC/HEIF/AVIF when pillow-heif is installed.
EXTS = (".jpg", ".jpeg", ".jpe", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic", ".heif", ".avif")
N = 32
K = 8
MAX_DISTINCT = 5000  # distinct hashes sharing one band that `similar` still compares pairwise
_COS = [[math.cos((2 * x + 1) * u * math.pi / (2 * N)) for x in range(N)] for u in range(K)]


def available():
    try:
        import PIL  # noqa: F401
    except ImportError:
        return False
    return True


def _register_heif():
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except ImportError:  # HEIC files then come out as 'unsupported', once
        pass


def phash_pixels(px):
    """64-bit pHash (unsigned int) of an N*N list of greyscale values (row-major)."""
    rows = [[sum(px[y * N + x] * _COS[u][x] for x in range(N)) for u in range(K)] for y in range(N)]
    dct = [[sum(rows[y][u] * _COS[v][y] for y in range(N)) for u in range(K)] for v in range(K)]
    flat = [d for r in dct for d in r]
    rest = sorted(flat[1:])  # median without the DC term, which only carries overall brightness
    med = (rest[len(rest) // 2 - 1] + rest[len(rest) // 2]) / 2
    h = 0
    for d in flat:
        h = (h << 1) | (d > med)
    return h


def phash_file(path):
    """(hash, width, height) of an image file; raises on anything Pillow cannot open."""
    from PIL import Image, ImageOps

    with Image.open(path) as im:
        w, h = im.size
        im.draft("L", (N * 4, N * 4))  # JPEG: decode at a reduced size, much faster for big photos
        im = ImageOps.exif_transpose(im)
        im = im.convert("L").resize((N, N), Image.Resampling.LANCZOS)
        return phash_pixels(list(im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata())), w, h


def to_signed(h):
    return h - (1 << 64) if h >= 1 << 63 else h


def to_unsigned(h):
    return h + (1 << 64) if h < 0 else h


def distance(a, b):
    return (to_unsigned(a) ^ to_unsigned(b)).bit_count()


def pending_where():
    ext = " OR ".join(f"LOWER(f.path) LIKE '%{e}'" for e in EXTS)
    return (
        f"f.current=1 AND f.state='ok' AND ({ext}) AND NOT EXISTS "
        f"(SELECT 1 FROM visual_hashes v WHERE v.file_id=f.id AND v.algo='{ALGO}')"
    )


def _init_worker():
    _register_heif()
    if hasattr(os, "nice"):  # a background job: stay out of the way of whatever else runs on the machine
        os.nice(10)


def _work(fp):
    """Runs in a worker process: ('ok', hash, w, h) or (state,). Only computes; the parent does all the database work."""
    try:
        h, w, ht = phash_file(fp)
        return ("ok", to_signed(h), w, ht)
    except Exception as e:
        return ("unsupported" if type(e).__name__ == "UnidentifiedImageError" else "error",)


def _reuse(c, sha):
    """(hash, width, height) already computed for another file with the same SHA-256 (same bytes, same picture)."""
    if sha is None:
        return None
    return c.execute(
        "SELECT v.hash,v.width,v.height FROM files f JOIN visual_hashes v ON v.file_id=f.id "
        "WHERE f.sha256=? AND f.current=1 AND v.algo=? AND v.state='ok' LIMIT 1",
        (sha, ALGO),
    ).fetchone()


def hash_pending(c, seconds, only=None, stop_when=None, workers=2):
    """pHash of current image files on disk that have none, until the time budget is spent (resumable).
    A file with the same SHA-256 as one already hashed copies that hash instead of decoding again. Decoding runs in
    `workers` processes (default 2, niced; 1 = in this process); the database is only touched from this process."""
    from concurrent.futures import ProcessPoolExecutor
    from multiprocessing import get_context

    from .core import coll, should_yield

    if not available():
        print("visual hashing needs Pillow: pip install 'strata-filecat[visual]'", file=sys.stderr)
        return 0
    _register_heif()
    end = time.time() + seconds
    done = bad = reused = 0
    last = 0  # keyset cursor, so rows left pending (not on disk yet) are not fetched again in this slice
    yst = {"t": 0.0, "y": False}
    paths = {(cid, label): p for cid, label, p in c.execute("SELECT collection_id,label,path FROM roots")}
    q = (
        "SELECT f.id,f.collection_id,f.root,f.path,f.sha256 FROM files f WHERE "
        + pending_where()
        + (" AND f.collection_id=%d" % coll(c, only)["id"] if only else "")
        + " AND f.id>? ORDER BY f.id LIMIT 200"
    )
    pool = (
        ProcessPoolExecutor(workers, mp_context=get_context("spawn"), initializer=_init_worker) if workers > 1 else None
    )
    chunk = max(4, workers * 4)  # decodes in flight at once: the time budget and stop-when are rechecked between chunks

    def store(fid, res):
        nonlocal done, bad
        if res[0] == "ok":
            c.execute(
                "INSERT INTO visual_hashes(file_id,algo,state,hash,width,height) VALUES(?,?,?,?,?,?)",
                (fid, ALGO, "ok", res[1], res[2], res[3]),
            )
            done += 1
        else:
            c.execute("INSERT INTO visual_hashes(file_id,algo,state) VALUES(?,?,?)", (fid, ALGO, res[0]))
            bad += 1

    def flush(todo, twin):
        nonlocal reused, done, bad
        for fid, job in todo:
            store(fid, job.result() if pool else _work(job))
        c.commit()
        for fid, owner, fp in twin:  # same bytes as a file decoded just above
            r = c.execute(
                "SELECT state,hash,width,height FROM visual_hashes WHERE file_id=? AND algo=?", (owner, ALGO)
            ).fetchone()
            if r[0] == "error":  # an I/O failure belongs to that path, not to the bytes: try this path itself
                store(fid, _work(fp))
            else:
                c.execute(
                    "INSERT INTO visual_hashes(file_id,algo,state,hash,width,height) VALUES(?,?,?,?,?,?)",
                    (fid, ALGO, r[0], r[1], r[2], r[3]),
                )
                reused += 1
                done += r[0] == "ok"
                bad += r[0] != "ok"
        c.commit()

    try:
        while time.time() < end:
            rows = c.execute(q, (last,)).fetchall()
            c.commit()
            if not rows:
                break
            last = rows[-1][0]
            todo = []  # (file id, future or path)
            twin = []  # (file id, id of the same-SHA file being decoded in this chunk, own path)
            inflight = {}  # sha -> file id being decoded in this chunk
            for fid, cid, root, path, sha in rows:
                if time.time() >= end:
                    break
                if should_yield(stop_when, yst):  # another job needs the disk: same rule as the SHA-256 pass
                    end = 0
                    break
                base = paths.get((cid, root))
                fp = os.path.join(base, path) if base else None
                if fp is None or not os.path.exists(fp):
                    continue  # not on disk (yet): left pending, like the SHA-256 pass leaves a file it cannot read
                r = _reuse(c, sha)
                if r:
                    c.execute(
                        "INSERT INTO visual_hashes(file_id,algo,state,hash,width,height) VALUES(?,?,?,?,?,?)",
                        (fid, ALGO, "ok", r[0], r[1], r[2]),
                    )
                    reused += 1
                    done += 1
                    continue
                if sha is not None and sha in inflight:
                    twin.append((fid, inflight[sha], fp))
                    continue
                if sha is not None:
                    inflight[sha] = fid
                todo.append((fid, pool.submit(_work, fp) if pool else fp))
                if len(todo) >= chunk:
                    flush(todo, twin)
                    todo, twin, inflight = [], [], {}
            flush(todo, twin)  # what was collected before the budget ran out is finished; nothing new is started
    finally:
        if pool:
            pool.shutdown()
    left = c.execute("SELECT COUNT(*) FROM files f WHERE " + pending_where()).fetchone()[0]
    print(
        f"visual hash: {done} images hashed ({reused} reused from identical files), {bad} unreadable; still to hash: {left}"
    )
    return done


def similar(c, max_dist=6, across=False, limit=20, collection=None):
    """Groups of images whose pHashes are within `max_dist` bits (default 6 of 64), exact duplicates (same SHA-256)
    collapsed to one member so that the groups are *different files* that look alike. Banding finds the candidates:
    two hashes within d bits agree exactly on at least one of d+1 bands (pigeonhole)."""
    from .core import coll

    where = "f.current=1 AND f.state='ok' AND v.algo=? AND v.state='ok'" + (
        " AND f.collection_id=%d" % coll(c, collection)["id"] if collection else ""
    )
    items = [
        (to_unsigned(h), fid, cid, f"{cn}:{root}:{path}", bytes(sha) if sha else None)
        for fid, cid, cn, root, path, sha, h in c.execute(
            "SELECT f.id,f.collection_id,(SELECT name FROM collections WHERE id=f.collection_id),f.root,f.path,f.sha256,v.hash "
            f"FROM files f JOIN visual_hashes v ON v.file_id=f.id WHERE {where}",
            (ALGO,),
        )
    ]
    nb = max_dist + 1
    width = -(-64 // nb)
    buckets = {}
    for i, it in enumerate(items):
        for b in range(nb):
            buckets.setdefault((b, (it[0] >> (b * width)) & ((1 << width) - 1)), []).append(i)
    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    skipped = 0
    for members in buckets.values():
        if len(members) < 2:
            continue
        # Identical hashes (blank frames, screenshots of one app) are one point: join them, then compare the distinct
        # values only, so a crowded band costs the square of the distinct hashes, not of the files.
        by_val = {}
        for i in members:
            by_val.setdefault(items[i][0], []).append(i)
        for same in by_val.values():
            for i in same[1:]:
                parent[find(i)] = find(same[0])
        vals = list(by_val)
        if len(vals) > MAX_DISTINCT:
            skipped += 1
            continue
        for a in range(len(vals)):
            for b in range(a + 1, len(vals)):
                if (vals[a] ^ vals[b]).bit_count() <= max_dist:
                    i, j = by_val[vals[a]][0], by_val[vals[b]][0]
                    parent[find(i)] = find(j)
    if skipped:
        print(
            f"warning: {skipped} crowded hash bands skipped (> {MAX_DISTINCT} distinct hashes); some matches may be missing",
            file=sys.stderr,
        )
    groups = {}
    for i in range(len(items)):
        groups.setdefault(find(i), []).append(i)
    out = []
    for g in groups.values():
        if (
            len({items[i][4] or ("id", items[i][1]) for i in g}) < 2
        ):  # all the same bytes: an exact dup, not a visual one
            continue
        if across and len({items[i][2] for i in g}) < 2:
            continue
        out.append(g)
    out.sort(key=len, reverse=True)
    lines = []
    for g in out[:limit]:
        line = f"x{len(g)}  " + " | ".join(items[i][3][-60:] for i in g[:4])
        lines.append(line)
        print(line)
    print(f"{len(out)} groups of visually similar, byte-different images (distance <= {max_dist})")
    return lines
