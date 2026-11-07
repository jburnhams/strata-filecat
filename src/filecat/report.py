"""Reports: per collection and across collections."""
from .core import coll, roots_of

def gb(x): return f'{(x or 0)/1e9:,.1f} GB'

def report(c, name=None):
    for cid, n, prof in c.execute('SELECT id,name,profile FROM collections' + (' WHERE name=?' if name else '') + ' ORDER BY id', (name,) if name else ()).fetchall():
        print(f'== {n} [{prof}]  sources: {dict(c.execute("SELECT kind,COUNT(*) FROM sources WHERE collection_id=? GROUP BY kind", (cid,)).fetchall())}')
        for root, k, b, h in c.execute("SELECT root,COUNT(*),SUM(size),SUM(sha256 IS NOT NULL) FROM files WHERE collection_id=? AND current=1 AND state='ok' GROUP BY root", (cid,)):
            print(f'   {root}: {k:,} files, {gb(b)}; hashed {h:,} ({100*h/k:.0f}%)')
        sk = c.execute("SELECT COUNT(*),SUM(size) FROM files WHERE collection_id=? AND state='skipped-nested'", (cid,)).fetchone()
        gone = c.execute("SELECT COUNT(*) FROM files WHERE collection_id=? AND state='missing'", (cid,)).fetchone()[0]
        chg = c.execute("SELECT COUNT(*) FROM (SELECT path FROM files WHERE collection_id=? AND state IN('ok','missing') GROUP BY root,path HAVING COUNT(DISTINCT COALESCE(crc32,sha256,size))>1)", (cid,)).fetchone()[0]
        print(f'   skipped entries: {sk[0]:,} ({gb(sk[1])}); gone from disk: {gone:,}; paths with more than one version: {chg:,}')
        g, ex, red = c.execute("SELECT COUNT(*),COALESCE(SUM(n-1),0),COALESCE(SUM((n-1)*sz),0) FROM (SELECT COUNT(*) n,MAX(size) sz FROM files WHERE collection_id=? AND current=1 AND sha256 IS NOT NULL GROUP BY sha256 HAVING n>1)", (cid,)).fetchone()
        print(f'   identical content inside the collection: {g:,} groups, {ex:,} redundant files, {gb(red)}')
    if not name:
        g, ex, red = c.execute("SELECT COUNT(*),COALESCE(SUM(n-1),0),COALESCE(SUM((n-1)*sz),0) FROM (SELECT COUNT(*) n,MAX(size) sz FROM files WHERE current=1 AND sha256 IS NOT NULL GROUP BY sha256 HAVING COUNT(DISTINCT collection_id)>1)").fetchone()
        print(f'== across collections: {g:,} contents present in more than one collection ({ex:,} extra copies, {gb(red)})')
        cand = c.execute("SELECT COUNT(*),COALESCE(SUM((n-1)*sz),0) FROM (SELECT COUNT(*) n,MAX(size) sz FROM files WHERE current=1 AND crc32 IS NOT NULL GROUP BY size,crc32 HAVING n>1)").fetchone()
        print(f'== candidates by size+CRC32 (before hashing completes): {cand[0]:,} groups, {gb(cand[1])}')

def dups(c, min_size=1000000, limit=20, across=False, collection=None):
    having = 'n>1' + (' AND COUNT(DISTINCT collection_id)>1' if across else '')
    where = 'current=1 AND sha256 IS NOT NULL AND size>=?' + (' AND collection_id=%d' % coll(c, collection)['id'] if collection else '')
    out = []
    for h, n, sz in c.execute(f"SELECT hex(substr(sha256,1,6)),COUNT(*) n,MAX(size) sz FROM files WHERE {where} GROUP BY sha256 HAVING {having} ORDER BY (n-1)*sz DESC LIMIT ?", (min_size, limit)).fetchall():
        ps = [r[0] for r in c.execute("SELECT (SELECT name FROM collections WHERE id=collection_id)||':'||root||':'||path FROM files WHERE current=1 AND hex(substr(sha256,1,6))=? AND size=? LIMIT 4", (h, sz))]
        line = f'{h} x{n} {sz/1e6:,.1f} MB  ' + ' | '.join(p[-72:] for p in ps); out.append(line); print(line)
    return out

def collections(c):
    for cid, name, prof, note in c.execute('SELECT id,name,profile,COALESCE(note,"") FROM collections ORDER BY id'):
        n = c.execute('SELECT COUNT(*) FROM files WHERE collection_id=? AND current=1', (cid,)).fetchone()[0]
        print(f'{name} [{prof}] {n:,} files  {note}')
        for l, (p, auto) in roots_of(c, cid).items(): print(f'   {l}: {p}{"  (autoscan)" if auto else ""}')
