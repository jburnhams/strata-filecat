"""Collections, archive indexing, incremental scans and hashing."""
import hashlib, json, os, sys, tarfile, time, zipfile
from .profiles import load_profile

def coll(c, name):
    r = c.execute('SELECT id,name,profile,config FROM collections WHERE name=?', (name,)).fetchone()
    if not r: sys.exit(f'no such collection: {name} (filecat collection list)')
    return dict(id=r[0], name=r[1], profile=r[2], config=json.loads(r[3] or '{}'))

def roots_of(c, cid): return {l: (p, a) for l, p, a in c.execute('SELECT label,path,autoscan FROM roots WHERE collection_id=?', (cid,))}

def add_collection(c, name, profile='plain', roots=(), config=None, note=None):
    load_profile(profile)                                            # fail early if the plugin is missing
    with c:
        cid = c.execute('INSERT INTO collections(name,profile,note,config,created_at) VALUES(?,?,?,?,?)', (name, profile, note, json.dumps(config or {}), int(time.time()))).lastrowid
        for r in roots:
            lab, _, rest = r.partition('='); path, _, flag = rest.partition(',')
            c.execute('INSERT INTO roots(collection_id,label,path,autoscan) VALUES(?,?,?,?)', (cid, lab, os.path.abspath(os.path.expanduser(path)), 1 if flag == 'autoscan' else 0))
    return cid

def source(c, cid, name, kind, ts=None, size=None, mtime=None, entries=None):
    r = c.execute('SELECT id FROM sources WHERE collection_id=? AND name=?', (cid, name)).fetchone()
    if r: return r[0]
    return c.execute('INSERT INTO sources(collection_id,name,kind,export_ts,size,mtime,entries,ingested_at) VALUES(?,?,?,?,?,?,?,?)', (cid, name, kind, ts, size, mtime, entries, int(time.time()))).lastrowid

def add_version(c, cid, root, rel, size, crc, mtime, sid, ts, orig, inherit=True):
    """New row for a path; the row it replaces stops being current. Same size + CRC32 as the replaced version inherits its hash."""
    prev = c.execute('SELECT id,size,crc32,sha256 FROM files WHERE collection_id=? AND root=? AND path=? AND current=1', (cid, root, rel)).fetchone()
    sha = None
    if prev:
        c.execute('UPDATE files SET current=0 WHERE id=?', (prev[0],))
        if inherit and crc is not None and prev[1] == size and prev[2] == crc: sha = prev[3]
    c.execute('INSERT INTO files(collection_id,root,path,size,crc32,sha256,mtime,source_id,export_ts,orig_path) VALUES(?,?,?,?,?,?,?,?,?,?)', (cid, root, rel, size, crc, sha, mtime, sid, ts, orig))

def profile_for(c, cl, root_label, strip=None, skip=None):
    roots = roots_of(c, cl['id']); root_label = root_label or next(iter(roots))
    if root_label not in roots: sys.exit(f'collection {cl["name"]} has no root {root_label}')
    return root_label, load_profile(cl['profile'])(cl['config'], roots[root_label][0], strip, skip)

def read_index(arch):
    """[(entry name, size, crc32 or None, mtime)] from the archive's index (zip central directory / tar headers); no data is read."""
    if zipfile.is_zipfile(arch):
        with zipfile.ZipFile(arch) as z: return [(i.filename, i.file_size, i.CRC, int(time.mktime(i.date_time + (0, 0, -1)))) for i in z.infolist() if not i.is_dir()]
    with tarfile.open(arch) as t: return [(m.name, m.size, None, int(m.mtime)) for m in t if m.isreg()]

def ingest_archive(c, cl, arch, root_label=None, strip=None, skip=None):
    root_label, prof = profile_for(c, cl, root_label, strip, skip); name = os.path.basename(arch)
    if c.execute('SELECT 1 FROM sources WHERE collection_id=? AND name=?', (cl['id'], name)).fetchone(): print(f'{name}: already in catalogue'); return
    ents = read_index(arch); st = os.stat(arch); ts = prof.meta(name); sk = er = 0
    with c:
        sid = source(c, cl['id'], name, 'archive', ts, st.st_size, int(st.st_mtime), len(ents))
        for fn, size, crc, mt in ents:
            kind, rel, orig = prof.map(fn)
            if kind != 'ok':
                sk += kind == 'skip'; er += kind == 'error'
                c.execute('INSERT INTO files(collection_id,root,path,size,crc32,mtime,source_id,export_ts,state,current) VALUES(?,?,?,?,?,?,?,?,?,0)', (cl['id'], root_label, rel, size, crc, mt, sid, ts, 'skipped-nested' if kind == 'skip' else 'error'))
                continue
            add_version(c, cl['id'], root_label, rel, size, crc, mt, sid, ts, orig)
    print(f'{name}: {len(ents)} entries ({sk} skipped, {er} errors)')

def scan_root(c, cl, label, path):
    """Incremental walk. Unchanged = same size and (CRC32 known from an archive, or same mtime); changed -> new version row; vanished -> state 'missing'."""
    if not os.path.isdir(path): print(f'{cl["name"]}:{label}: {path} missing, skipped', file=sys.stderr); return
    gen = c.execute('SELECT COALESCE(MAX(seen_gen),0)+1 FROM files').fetchone()[0]          # a counter, not a timestamp: two scans in one second must stay distinguishable
    sid = source(c, cl['id'], 'scan:' + label, 'scan'); new = chg = same = 0
    sel = 'SELECT id,size,crc32,mtime FROM files WHERE collection_id=? AND root=? AND path=? AND current=1'
    for dp, dn, fns in os.walk(path):
        dn[:] = [d for d in dn if not d.startswith('.')]
        for fn in fns:
            if fn.startswith('.') or fn.endswith(('.partial', '.part')): continue
            fp = os.path.join(dp, fn)
            try: st = os.lstat(fp)
            except OSError: continue
            if os.path.islink(fp) or not os.path.isfile(fp): continue
            rel = os.path.relpath(fp, path).replace(os.sep, '/'); mt = int(st.st_mtime)         # always '/' in the catalogue, so one path means the same on every OS
            r = c.execute(sel, (cl['id'], label, rel)).fetchone()
            if r and r[1] == st.st_size and (r[2] is not None or r[3] == mt): c.execute('UPDATE files SET seen_gen=? WHERE id=?', (gen, r[0])); same += 1
            else:
                add_version(c, cl['id'], label, rel, st.st_size, None, mt, sid, None, None, inherit=False)
                c.execute('UPDATE files SET seen_gen=? WHERE collection_id=? AND root=? AND path=? AND current=1', (gen, cl['id'], label, rel)); chg += bool(r); new += not r
        c.commit()
    gone = c.execute("UPDATE files SET current=0, state='missing' WHERE collection_id=? AND root=? AND current=1 AND state='ok' AND (seen_gen IS NULL OR seen_gen<>?)", (cl['id'], label, gen)).rowcount
    c.commit(); print(f'{cl["name"]}:{label}: {new:,} new, {chg:,} changed, {same:,} unchanged, {gone:,} gone')

def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb', buffering=0) as f:
        while True:
            b = f.read(1 << 22)
            if not b: break
            h.update(b)
    return h.digest()

def hash_pending(c, seconds, only=None):
    """SHA-256 of current files on disk that have none, oldest rows first, until the time budget is spent (resumable)."""
    end = time.time() + seconds; done = nbytes = 0
    paths = {(cid, l): p for cid, l, p in c.execute('SELECT collection_id,label,path FROM roots')}
    q = "SELECT id,collection_id,root,path,size FROM files WHERE sha256 IS NULL AND current=1 AND state='ok'" + (' AND collection_id=%d' % coll(c, only)['id'] if only else '') + ' ORDER BY id LIMIT 200'
    while time.time() < end:
        rows = c.execute(q).fetchall()
        if not rows: break
        for fid, cid, root, path, size in rows:
            if time.time() >= end: break
            base = paths.get((cid, root))
            if base is None:                                                      # a collection may have been added by another process since this slice started: look again before giving up
                paths = {(i, l): p for i, l, p in c.execute('SELECT collection_id,label,path FROM roots')}; base = paths.get((cid, root))
            if base is None: c.execute("UPDATE files SET state='error' WHERE id=?", (fid,)); c.commit(); continue
            fp = os.path.join(base, path)
            try:
                if os.stat(fp).st_size != size: c.execute("UPDATE files SET state='size-mismatch' WHERE id=?", (fid,)); c.commit(); continue
                digest = sha256_file(fp)                   # slow (a big video takes minutes): no write transaction may be open meanwhile, or every other filecat call waits
                c.execute('UPDATE files SET sha256=? WHERE id=?', (digest, fid)); c.commit(); done += 1; nbytes += size
            except FileNotFoundError: c.execute("UPDATE files SET state='missing' WHERE id=?", (fid,)); c.commit()
            except OSError as e: print('hash error', fp[:100], e, file=sys.stderr)
        c.commit()
    left = c.execute("SELECT COUNT(*),COALESCE(SUM(size),0) FROM files WHERE sha256 IS NULL AND current=1 AND state='ok'").fetchone()
    print(f'hashed {done} files ({nbytes/1e9:.1f} GB); still to hash: {left[0]} files ({left[1]/1e9:.1f} GB)')
    return done

def run_all(c, seconds):
    """For every collection: ingest what its profile says is pending, scan autoscan roots; then hash."""
    for cid, name in c.execute('SELECT id,name FROM collections ORDER BY id').fetchall():
        cl = coll(c, name); cls = load_profile(cl['profile'])
        if hasattr(cls, 'pending_archives'):
            for arch in cls.pending_archives(cl['config']):
                if not c.execute('SELECT 1 FROM sources WHERE collection_id=? AND name=?', (cid, os.path.basename(arch))).fetchone(): ingest_archive(c, cl, arch)
        for l, (p, auto) in roots_of(c, cid).items():
            if auto: scan_root(c, cl, l, p)
    return hash_pending(c, seconds)
