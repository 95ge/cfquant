"""Execute the embedded implementation without importing the SDK package."""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("path", sorted((ROOT / "qmt_scripts").rglob("CFQUANT_LITE*.py")), ids=lambda path:path.stem)
def test_standalone_feed_shares_native_handle(path):
    source = path.read_text(encoding="gbk")
    embedded = source.split("# BEGIN GENERATED SHARED QUOTES\n",1)[1].split("# END GENERATED SHARED QUOTES",1)[0]
    assert embedded.strip() == (ROOT / "cfquant/shared_quotes.py").read_text(encoding="utf-8").strip()
    ast.parse(embedded, feature_version=(3,6))
    namespace = {}
    exec(compile(embedded,str(path),"exec"),namespace)
    subscriptions, releases = [], []
    def subscribe(scope, callback, generation):
        subscriptions.append((scope,callback))
        return 99
    feed = namespace["SharedQuoteFeed"](subscribe,lambda handle:releases.append(handle),
                                         initial_scope=["SH","SZ","BJ"],idle_seconds=0)
    try:
        first = feed.acquire("user",["SH"])
        second = feed.acquire("algo",["600000.SH"],purpose="algo")
        assert len(subscriptions) == 1
        subscriptions[0][1]({"600000.SH":{"lastPrice":10}})
        assert feed.snapshot("600000.SH")["quote"]["lastPrice"] == 10
        feed.release(first)
        assert not releases
        feed.release(second)
        assert releases == [99]
    finally:
        feed.close()
