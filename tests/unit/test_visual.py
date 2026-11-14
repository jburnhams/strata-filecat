import random

from PIL import Image

from filecat import core, visual


def pic(path, seed=1, size=(200, 150), fmt=None, **kw):
    """A synthetic picture with structure (random blobs), so that different seeds give clearly different pHashes."""
    rnd = random.Random(seed)
    im = Image.new("RGB", (64, 48))
    px = im.load()
    for _ in range(12):
        x, y, r, col = (
            rnd.randrange(64),
            rnd.randrange(48),
            rnd.randrange(6, 20),
            tuple(rnd.randrange(256) for _ in range(3)),
        )
        for i in range(max(0, x - r), min(64, x + r)):
            for j in range(max(0, y - r), min(48, y + r)):
                px[i, j] = col
    im.resize(size).save(path, fmt, **kw)


def catalogue(db, tree, files, name="c"):
    root = tree(name, {})
    root.mkdir(exist_ok=True)
    for rel, maker in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        maker(root / rel)
    core.add_collection(db, name, roots=[f"r={root}"])
    cl = core.coll(db, name)
    core.scan_root(db, cl, "r", str(root))
    return cl


def test_phash_matches_resized_recompressed_and_other_formats_but_not_other_pictures(tmp_path):
    pic(tmp_path / "a.png", 1, (400, 300))
    pic(tmp_path / "a_small.jpg", 1, (100, 75), quality=60)
    pic(tmp_path / "a.webp", 1, (300, 225))
    pic(tmp_path / "b.png", 2, (400, 300))
    h = {n: visual.phash_file(tmp_path / n)[0] for n in ("a.png", "a_small.jpg", "a.webp", "b.png")}
    assert visual.distance(h["a.png"], h["a_small.jpg"]) <= 6
    assert visual.distance(h["a.png"], h["a.webp"]) <= 6
    assert visual.distance(h["a.png"], h["b.png"]) > 12
    assert visual.phash_file(tmp_path / "a.png")[1:] == (400, 300)


def test_exif_orientation_is_applied(tmp_path):
    pic(tmp_path / "up.jpg", 3, (300, 200))
    im = Image.open(tmp_path / "up.jpg").rotate(90, expand=True)
    exif = Image.Exif()
    exif[0x0112] = 6  # stored rotated, tagged "rotate 90 CW to display": the same picture once orientation is applied
    im.save(tmp_path / "phone.jpg", exif=exif)
    assert visual.distance(visual.phash_file(tmp_path / "up.jpg")[0], visual.phash_file(tmp_path / "phone.jpg")[0]) <= 8


def test_signed_roundtrip():
    for h in (0, 1, (1 << 63) - 1, 1 << 63, (1 << 64) - 1):
        assert visual.to_unsigned(visual.to_signed(h)) == h
        assert -(1 << 63) <= visual.to_signed(h) < 1 << 63


def test_hash_pending_hashes_images_only_once_and_marks_bad_files(db, tree, capsys):
    cl = catalogue(
        db,
        tree,
        {
            "a.png": lambda p: pic(p, 1),
            "sub/B.JPG": lambda p: pic(p, 2),
            "notes.txt": lambda p: p.write_text("hi"),
            "broken.png": lambda p: p.write_bytes(b"not an image"),
        },
    )
    assert visual.hash_pending(db, 30) == 2
    states = dict(db.execute("SELECT f.path,v.state FROM visual_hashes v JOIN files f ON f.id=v.file_id").fetchall())
    assert states == {"a.png": "ok", "sub/B.JPG": "ok", "broken.png": "unsupported"}
    assert visual.hash_pending(db, 30) == 0  # nothing left, and the broken file is not retried
    assert "0 unreadable" in capsys.readouterr().out
    core.scan_root(db, cl, "r", core.roots_of(db, cl["id"])["r"][0])
    assert visual.hash_pending(db, 30) == 0


def test_changed_file_is_hashed_again(db, tree):
    cl = catalogue(db, tree, {"a.png": lambda p: pic(p, 1)})
    visual.hash_pending(db, 30)
    root = core.roots_of(db, cl["id"])["r"][0]
    pic(root + "/a.png", 5, (300, 200))
    core.scan_root(db, cl, "r", root)
    assert visual.hash_pending(db, 30) == 1
    assert db.execute("SELECT COUNT(*) FROM visual_hashes").fetchone()[0] == 2  # one per version row


def test_similar_finds_different_files_of_the_same_picture_across_collections(db, tree, capsys):
    catalogue(db, tree, {"x/a.png": lambda p: pic(p, 1, (400, 300)), "x/other.png": lambda p: pic(p, 9)}, name="one")
    catalogue(db, tree, {"y/a_copy.jpg": lambda p: pic(p, 1, (120, 90), quality=70)}, name="two")
    catalogue(db, tree, {"z/exact.png": lambda p: pic(p, 1, (400, 300))}, name="three")
    core.hash_pending(db, 30)
    visual.hash_pending(db, 30)
    capsys.readouterr()
    lines = visual.similar(db)
    assert len(lines) == 1 and lines[0].startswith("x3") and "other.png" not in lines[0]
    assert len(visual.similar(db, across=True)) == 1
    assert visual.similar(db, collection="one") == []  # only one picture in that collection
    assert len(visual.similar(db, max_dist=0, across=True)) == 1  # synthetic copies hash to the very same bits


def test_exact_copies_alone_are_not_reported_as_similar(db, tree):
    catalogue(db, tree, {"a.png": lambda p: pic(p, 1), "copy.png": lambda p: pic(p, 1)})
    core.hash_pending(db, 30)
    visual.hash_pending(db, 30)
    assert visual.similar(db) == []


def test_cli_and_report(tmp_path, monkeypatch, capsys):
    from filecat import cli

    monkeypatch.setenv("FILECAT_DB", str(tmp_path / "cat.db"))
    (tmp_path / "pics").mkdir()
    pic(tmp_path / "pics" / "a.png", 1)
    pic(tmp_path / "pics" / "b.jpg", 1, (90, 60))
    cli.main(["collection", "add", "p", "--root", f"r={tmp_path / 'pics'},autoscan"])
    cli.main(["run", "--seconds", "30"])
    cli.main(["report", "p"])
    out = capsys.readouterr().out
    assert "visual hashes: 2 image files (0 unreadable)" in out
    cli.main(["similar", "--distance", "8"])
    assert "x2" in capsys.readouterr().out
    cli.main(["visual-hash", "--collection", "p"])


def test_without_pillow_the_pass_is_skipped_with_a_message(db, monkeypatch, capsys):
    monkeypatch.setattr(visual, "available", lambda: False)
    assert visual.hash_pending(db, 5) == 0
    assert "strata-filecat[visual]" in capsys.readouterr().err


def test_files_not_on_disk_do_not_stall_the_slice(db, tree, monkeypatch):
    """More than one batch (200) of pending images that are absent, then a real one: the real one is still reached."""
    root = tree("c", {"z.png": b""})
    pic(root / "z.png", 1)
    core.add_collection(db, "c", roots=[f"r={root}"])
    cid = core.coll(db, "c")["id"]
    for i in range(250):  # ids below z.png's, as after indexing an archive that is not extracted yet
        db.execute(
            "INSERT INTO files(collection_id,root,path,size,source_id) VALUES(?,?,?,?,?)",
            (cid, "r", f"gone{i}.jpg", 1, 1),
        )
    db.commit()
    core.scan_root(db, core.coll(db, "c"), "r", str(root))
    assert visual.hash_pending(db, 30) == 1


def test_stop_when_pauses_the_visual_pass(db, tree):
    catalogue(db, tree, {"a.png": lambda p: pic(p, 1)})
    assert visual.hash_pending(db, 30, stop_when="true") == 0
    assert visual.hash_pending(db, 30, stop_when="false") == 1


def test_similar_matches_in_a_crowded_band_and_warns_when_it_must_skip(db, tree, monkeypatch, capsys):
    catalogue(db, tree, {"a.png": lambda p: pic(p, 1), "b.jpg": lambda p: pic(p, 1, (90, 60))})
    core.hash_pending(db, 30)
    visual.hash_pending(db, 30)
    monkeypatch.setattr(
        visual, "MAX_DISTINCT", 1
    )  # force the "crowded" path: two distinct hashes in a band is too many
    capsys.readouterr()
    visual.similar(db)
    assert "crowded hash bands skipped" in capsys.readouterr().err
    monkeypatch.setattr(visual, "MAX_DISTINCT", 5000)
    assert len(visual.similar(db)) <= 1
