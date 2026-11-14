import json
import os

import pytest

from filecat import cli, core, labels
from filecat.profiles import Plain


class Labeller(Plain):
    """A fake profile: labels come from `<file>.json` next to it ({"people": [...]}); no sidecar = no label source."""

    label_exts = (".jpg", ".png")

    def __init__(self, cfg, root, strip=None, skip=None):
        super().__init__(cfg, root, strip, skip)
        self.root = root

    def labels(self, rel):
        p = os.path.join(self.root, rel + ".json")
        if not os.path.exists(p):
            return None
        d = json.load(open(p))  # a malformed file raises ValueError (JSONDecodeError)
        return [("person", n) for n in d.get("people", [])] + [("album", a) for a in [d.get("album")] if a]


@pytest.fixture
def fake(monkeypatch):
    class EP:
        name = "lab"

        def load(self):
            return Labeller

    monkeypatch.setattr("importlib.metadata.entry_points", lambda group: [EP()])


def setup(db, tree, files):
    root = tree("c", {k: (json.dumps(v).encode() if isinstance(v, dict) else v) for k, v in files.items()})
    core.add_collection(db, "c", profile="lab", roots=[f"r={root}"])
    core.scan_root(db, core.coll(db, "c"), "r", str(root))
    return root


def test_labels_are_read_once_and_stored(db, tree, fake, capsys):
    setup(
        db,
        tree,
        {
            "a.jpg": b"x",
            "a.jpg.json": {"people": ["Ann", "Bob", "Ann"], "album": "Trip"},
            "b.png": b"y",  # no sidecar
            "c.jpg": b"z",
            "c.jpg.json": b"{not json",  # unreadable
            "d.txt": b"t",  # not a label extension
        },
    )
    assert labels.read_pending(db, 30) == 1
    got = sorted(
        db.execute("SELECT f.path,l.kind,l.value FROM file_labels l JOIN files f ON f.id=l.file_id").fetchall()
    )
    assert got == [("a.jpg", "album", "Trip"), ("a.jpg", "person", "Ann"), ("a.jpg", "person", "Bob")]
    states = dict(db.execute("SELECT f.path,s.state FROM label_scans s JOIN files f ON f.id=s.file_id").fetchall())
    assert states == {"a.jpg": "ok", "b.png": "none", "c.jpg": "error"}
    assert "1 files labelled (3 labels), 1 without a label source, 1 unreadable" in capsys.readouterr().out
    assert labels.read_pending(db, 30) == 0  # nothing pending: not read again


def test_a_changed_file_is_looked_at_again_and_run_reads_labels(db, tree, fake):
    root = setup(db, tree, {"a.jpg": b"x", "a.jpg.json": {"people": ["Ann"]}})
    core.run_all(db, 10, workers=1)
    assert db.execute("SELECT COUNT(*) FROM file_labels").fetchone()[0] == 1
    (root / "a.jpg").write_bytes(b"changed!")  # new size: a new version row, which has no scan yet
    (root / "a.jpg.json").write_text(json.dumps({"people": ["Ann", "Cy"]}))
    core.scan_root(db, core.coll(db, "c"), "r", str(root))
    assert labels.read_pending(db, 30) == 1
    assert len(labels.find(db, "person", "Cy")) == 1  # the new version has both names; the old row is not current


def test_find_summary_and_report_and_cli(db, tree, fake, capsys):
    setup(
        db, tree, {"a.jpg": b"x", "a.jpg.json": {"people": ["Ann"]}, "b.jpg": b"y", "b.jpg.json": {"people": ["Ann"]}}
    )
    cli.main(["labels"])
    assert labels.summary(db, 1) == [("person", 1, 2)]
    cli.main(["labels", "--find", "person=Ann", "--collection", "c"])
    out = capsys.readouterr().out
    assert sorted(l for l in out.splitlines() if l.startswith("c:r:") and "." in l.split(":")[-1] and "jpg" in l) == [
        "c:r:a.jpg",
        "c:r:b.jpg",
    ]
    cli.main(["report", "c"])
    assert "labels 'person': 2 on current files, 1 distinct" in capsys.readouterr().out


def test_profiles_without_labels_are_skipped(db, tree, capsys):
    root = tree("p", {"a.jpg": b"x"})
    core.add_collection(db, "p", roots=[f"r={root}"])
    core.scan_root(db, core.coll(db, "p"), "r", str(root))
    assert labels.read_pending(db, 5) == 0
    assert db.execute("SELECT COUNT(*) FROM label_scans").fetchone()[0] == 0


def test_the_budget_is_checked_per_file_and_no_write_transaction_is_open_while_reading(db, tree, fake, monkeypatch):
    from filecat.db import connect

    setup(db, tree, {f"p{i}.jpg": b"x" for i in range(6)})
    other = connect()
    seen = []

    def slow(self, rel):
        # a second connection can write while a label source is being read: no write lock is held by the reader
        other.execute("INSERT INTO collections(name) VALUES(?)", (f"w{len(seen)}",))
        other.commit()
        seen.append(rel)
        monkeypatch.setattr(
            labels.time, "time", lambda t=[__import__("time").time()]: t.__setitem__(0, t[0] + 10) or t[0]
        )
        return None

    monkeypatch.setattr(Labeller, "labels", slow)
    labels.read_pending(db, 15)
    assert 1 <= len(seen) < 6  # the clock jumps 10 s per file: the slice ends early, the rest stays pending
    assert db.execute("SELECT COUNT(*) FROM label_scans").fetchone()[0] == len(seen)
    other.close()
