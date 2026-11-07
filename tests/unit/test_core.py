import os, zipfile
import pytest
from filecat import core, report
from filecat.profiles import Plain, load_profile

def one(db, sql, *a): return db.execute(sql, a).fetchone()

def test_scan_new_changed_unchanged_gone(db, tree, capsys):
    root = tree('flickr', {'2019/a.jpg': b'PHOTO-A', '2020/u.jpg': b'UNIQUE', '2020/c.txt': b'OLD'})
    core.add_collection(db, 'flickr', roots=[f'photos={root},autoscan']); cl = core.coll(db, 'flickr')
    core.scan_root(db, cl, 'photos', str(root)); assert '3 new, 0 changed, 0 unchanged, 0 gone' in capsys.readouterr().out
    (root / '2020/c.txt').write_bytes(b'NEWER-CONTENT'); os.utime(root / '2020/c.txt', (2_000_000_000, 2_000_000_000))
    (root / '2020/u.jpg').unlink(); (root / 'new.png').write_bytes(b'x')
    core.scan_root(db, cl, 'photos', str(root)); assert '1 new, 1 changed, 1 unchanged, 1 gone' in capsys.readouterr().out
    assert one(db, "SELECT COUNT(*) FROM files WHERE path='2020/c.txt'")[0] == 2             # history kept
    assert one(db, "SELECT size FROM files WHERE path='2020/c.txt' AND current=1")[0] == 13
    assert one(db, "SELECT state,current FROM files WHERE path='2020/u.jpg'") == ('missing', 0)

def test_scan_ignores_hidden_partial_and_symlinks(db, tree):
    root = tree('c', {'ok.txt': b'1', '.hidden': b'2', 'x.partial': b'3', '.dir/inner.txt': b'4'}); os.symlink(root / 'ok.txt', root / 'link.txt')
    core.add_collection(db, 'c', roots=[f'r={root}']); core.scan_root(db, core.coll(db, 'c'), 'r', str(root))
    assert [r[0] for r in db.execute('SELECT path FROM files')] == ['ok.txt']

def test_hash_and_cross_collection_duplicates(db, tree, capsys):
    f = tree('flickr', {'a.jpg': b'PHOTO-A', 'u.jpg': b'ONLY-FLICKR'}); p = tree('phone', {'IMG_1.jpg': b'PHOTO-A', 'IMG_1_copy.jpg': b'PHOTO-A'})
    core.add_collection(db, 'flickr', roots=[f'photos={f}']); core.add_collection(db, 'phone', roots=[f'dcim={p}'])
    for n, r, d in (('flickr', 'photos', f), ('phone', 'dcim', p)): core.scan_root(db, core.coll(db, n), r, str(d))
    assert core.hash_pending(db, 30) == 4
    out = report.dups(db, min_size=1, across=True)
    assert len(out) == 1 and out[0].split()[1] == 'x3'
    report.report(db); text = capsys.readouterr().out
    assert '1 contents present in more than one collection (2 extra copies' in text and 'identical content inside the collection: 1 groups' in text
    assert report.dups(db, min_size=1, across=True, collection='flickr') == []             # only one flickr file in that group

def test_hash_marks_missing_and_size_mismatch(db, tree):
    root = tree('c', {'a.txt': b'12345', 'b.txt': b'12345'}); core.add_collection(db, 'c', roots=[f'r={root}']); core.scan_root(db, core.coll(db, 'c'), 'r', str(root))
    (root / 'a.txt').unlink(); (root / 'b.txt').write_bytes(b'longer now')
    assert core.hash_pending(db, 30) == 0
    assert {r[0]: r[1] for r in db.execute('SELECT path,state FROM files')} == {'a.txt': 'missing', 'b.txt': 'size-mismatch'}

def make_zip(path, files):
    with zipfile.ZipFile(path, 'w') as z:
        for k, v in files.items(): z.writestr(k, v)
    return str(path)

def test_ingest_archive_strip_skip_and_versions(db, tmp_path, capsys):
    core.add_collection(db, 'amazon', roots=[f'data={tmp_path}'], config={'strip': '1', 'skip': ['Junk']}); cl = core.coll(db, 'amazon')
    z1 = make_zip(tmp_path / 'one.zip', {'Amz/Orders/o1.csv': 'a,b', 'Amz/Junk/j.bin': 'zz', 'Amz/Orders/o2.csv': 'c,d'})
    z2 = make_zip(tmp_path / 'two.zip', {'Amz/Orders/o1.csv': 'a,b', 'Amz/Orders/o2.csv': 'CHANGED!'})
    core.ingest_archive(db, cl, z1); assert '3 entries (1 skipped, 0 errors)' in capsys.readouterr().out
    core.ingest_archive(db, cl, z1); assert 'already in catalogue' in capsys.readouterr().out
    core.ingest_archive(db, cl, z2, strip=1, skip=['Junk'])
    rows = {(r[0], r[1], r[2]) for r in db.execute('SELECT path,state,current FROM files')}
    assert ('Junk/j.bin', 'skipped-nested', 0) in rows and ('Orders/o1.csv', 'ok', 0) in rows and ('Orders/o1.csv', 'ok', 1) in rows
    assert one(db, "SELECT COUNT(*) FROM files WHERE path='Orders/o2.csv'")[0] == 2 and one(db, "SELECT size FROM files WHERE path='Orders/o2.csv' AND current=1")[0] == 8
    assert one(db, "SELECT sha256 IS NULL FROM files WHERE path='Orders/o1.csv' AND current=1")[0] == 1      # no hash yet (nothing on disk)

def test_same_size_and_crc_inherits_the_hash(db, tmp_path):
    core.add_collection(db, 'c', roots=[f'r={tmp_path}']); cl = core.coll(db, 'c')
    core.ingest_archive(db, cl, make_zip(tmp_path / 'a.zip', {'x/f.txt': 'same'}), strip=1)
    db.execute("UPDATE files SET sha256=X'AA'"); db.commit()
    core.ingest_archive(db, cl, make_zip(tmp_path / 'b.zip', {'x/f.txt': 'same'}), strip=1)
    assert one(db, 'SELECT hex(sha256) FROM files WHERE current=1')[0] == 'AA'

def test_plain_profile_maps_and_rejects_traversal():
    p = Plain({}, None, strip=1, skip=['Skip/'])
    assert p.map('top/a/b.txt') == ('ok', 'a/b.txt', 'top/a/b.txt')
    assert p.map('top/Skip/x') == ('skip', 'Skip/x', None) and p.map('top') == ('skip', 'top', None)
    assert p.map('top/../../etc/passwd')[1] == 'etc/passwd'                      # '..' components are dropped, never followed

def test_unknown_profile_is_an_error(db):
    with pytest.raises(SystemExit): load_profile('nope')
    with pytest.raises(SystemExit): core.add_collection(db, 'x', profile='nope')

def test_profile_plugin_and_pending_archives(db, tmp_path, monkeypatch):
    class Fake(Plain):
        @classmethod
        def pending_archives(cls, cfg): return [cfg['dir'] + '/p1.zip']
        def meta(self, name): return '2026'
    class EP:
        name = 'fake'
        def load(self): return Fake
    monkeypatch.setattr('importlib.metadata.entry_points', lambda group: [EP()])
    make_zip(tmp_path / 'p1.zip', {'T/a.txt': 'x'})
    core.add_collection(db, 'fk', profile='fake', roots=[f'r={tmp_path}'], config={'dir': str(tmp_path), 'strip': '1'})
    core.run_all(db, 5); core.run_all(db, 5)                                    # the second run must not ingest again
    assert one(db, 'SELECT COUNT(*) FROM sources WHERE kind="archive"')[0] == 1 and one(db, 'SELECT export_ts FROM sources WHERE kind="archive"')[0] == '2026'

def test_cli_end_to_end(tmp_path, monkeypatch, capsys):
    from filecat.cli import main
    monkeypatch.setenv('FILECAT_DB', str(tmp_path / 'cli.db')); d = tmp_path / 'data'; d.mkdir(); (d / 'a.txt').write_text('hello')
    main(['collection', 'add', 'demo', '--root', f'r={d},autoscan', '--note', 'demo']); main(['run', '--seconds', '10']); main(['collection', 'list']); main(['report']); main(['dups', '--min-size', '1'])
    out = capsys.readouterr().out
    assert 'collection demo added' in out and 'demo [plain] 1 files' in out and 'r: ' in out and 'hashed 1 files' in out and '== demo [plain]' in out

def test_other_invocations_are_not_blocked_while_a_big_file_is_being_hashed(db, tmp_path, monkeypatch):
    """Hashing a multi-GB file takes minutes; a second filecat call (the extractor hook, a report) must not wait for it."""
    import sqlite3, threading
    from filecat.db import connect
    d = tmp_path / 'd'; d.mkdir(); (d / 'a.bin').write_bytes(b'1'); (d / 'b.bin').write_bytes(b'22')
    core.add_collection(db, 'c', roots=[f'r={d}']); core.scan_root(db, core.coll(db, 'c'), 'r', str(d))
    started, release, result = threading.Event(), threading.Event(), {}
    real = core.sha256_file
    def slow(p):
        if p.endswith('b.bin'): started.set(); release.wait(10)          # b.bin is hashed second: the first file's row has just been written
        return real(p)
    monkeypatch.setattr(core, 'sha256_file', slow)
    t = threading.Thread(target=lambda: result.update(n=core.hash_pending(connect(), 30))); t.start()
    assert started.wait(10)
    other = sqlite3.connect(str(tmp_path / 'cat.db'), timeout=0.5)         # would raise 'database is locked' if the hasher held a write transaction
    other.execute("UPDATE collections SET note='x'"); other.commit(); connect()                    # and connect() must not need the write lock either
    release.set(); t.join(); assert result['n'] == 2
