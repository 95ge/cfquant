"""Bounded, content-keyed parsing for the source synchronizers.

Callers only inspect these trees. Never mutate a cached node: source edits
produce a new string and therefore a new cache entry, including line offsets.
"""

import ast
from functools import lru_cache


@lru_cache(maxsize=8)
def parse_source(source, *, feature_version=None):
    return ast.parse(source, feature_version=feature_version)
