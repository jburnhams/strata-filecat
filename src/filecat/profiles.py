"""Profiles turn an archive entry name into the path stored in the catalogue.

A profile is a class with `__init__(cfg, root, strip=None, skip=None)`, `meta(archive_name) -> export timestamp or None` and
`map(entry_name) -> (kind, path, orig)` where kind is 'ok' (path = stored path, orig = original path if it had to change, else None),
'skip' (not extracted; path = what to record) or 'error'. It may also have `pending_archives(cfg)`: a classmethod yielding archive paths
that should be ingested automatically by `filecat run`, in the order they were extracted.
`plain` ships here; others are plugins registered in the entry point group `filecat.profiles` (e.g. `takeout` from strata-takeout).
"""
import importlib.metadata

class Plain:
    """Entry name minus `strip` leading components, minus `skip` prefixes (from the collection config or the command line)."""
    def __init__(s, cfg, root, strip=None, skip=None):
        s.strip = int(cfg.get('strip', 0) if strip is None else strip)
        s.skip = [k.strip('/') for k in (cfg.get('skip', []) if skip is None else skip)]
    def meta(s, name): return None
    def map(s, name):
        parts = [p for p in name.replace('\\', '/').split('/') if p not in ('', '.', '..')]; orig = '/'.join(parts)
        rest = '/'.join(parts[s.strip:])
        if not rest: return ('skip', orig, None)
        if any(rest == k or rest.startswith(k + '/') for k in s.skip): return ('skip', rest, None)
        return ('ok', rest, orig if orig != rest else None)

def load_profile(name):
    if name == 'plain': return Plain
    for ep in importlib.metadata.entry_points(group='filecat.profiles'):
        if ep.name == name: return ep.load()
    raise SystemExit(f'unknown profile {name!r}: install the package that provides it (entry point group filecat.profiles)')
