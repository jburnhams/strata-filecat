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


def hash_pending(c, seconds, only=None):
    """pHash of current image files on disk that have none, until the time budget is spent (resumable)."""
    from .core import coll

    if not available():
        print("visual hashing needs Pillow: pip install 'strata-filecat[visual]'", file=sys.stderr)
        return 0
    _register_heif()
    end = time.time() + seconds
    done = bad = 0
    paths = {(cid, label): p for cid, label, p in c.execute("SELECT collection_id,label,path FROM roots")}
    q = (
        "SELECT f.id,f.collection_id,f.root,f.path FROM files f WHERE "
        + pending_where()
        + (" AND f.collection_id=%d" % coll(c, only)["id"] if only else "")
        + " ORDER BY f.id LIMIT 200"
    )
    while time.time() < end:
        rows = c.execute(q).fetchall()
        c.commit()
        if not rows:
            break
        for fid, cid, root, path in rows:
            if time.time() >= end:
                break
            base = paths.get((cid, root))
            fp = os.path.join(base, path) if base else None
            if fp is None or not os.path.exists(fp):
                continue  # not on disk (yet): left pending, like the SHA-256 pass leaves a file it cannot read
            try:
                h, w, ht = phash_file(fp)
                c.execute(
                    "INSERT INTO visual_hashes(file_id,algo,state,hash,width,height) VALUES(?,?,?,?,?,?)",
                    (fid, ALGO, "ok", to_signed(h), w, ht),
                )
                done += 1
            except Exception as e:
                c.execute(
                    "INSERT INTO visual_hashes(file_id,algo,state) VALUES(?,?,?)",
                    (fid, ALGO, "unsupported" if type(e).__name__ == "UnidentifiedImageError" else "error"),
                )
                bad += 1
            c.commit()
        c.commit()
    left = c.execute("SELECT COUNT(*) FROM files f WHERE " + pending_where()).fetchone()[0]
    print(f"visual hash: {done} images hashed, {bad} unreadable; still to hash: {left}")
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

    for members in buckets.values():
        if len(members) < 2 or len(members) > 2000:  # a huge bucket is a flat/blank image band, not a match
            continue
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                i, j = members[a], members[b]
                if find(i) != find(j) and (items[i][0] ^ items[j][0]).bit_count() <= max_dist:
                    parent[find(i)] = find(j)
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
