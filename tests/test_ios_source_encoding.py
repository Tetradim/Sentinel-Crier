from pathlib import Path


def test_swift_sources_are_utf8():
    """Non-UTF8 source can crash Swift dependency scanning before diagnostics."""
    root = Path(__file__).resolve().parents[1] / "ios"
    for source in root.rglob("*.swift"):
        source.read_bytes().decode("utf-8")
