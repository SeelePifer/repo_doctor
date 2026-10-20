from repodoctor.textutil import chunk_ranges, files_in_diff, snippet_matches


def test_chunk_ranges_overlap() -> None:
    ranges = chunk_ranges(100, size=80, overlap=15)
    assert ranges == [(1, 80), (66, 100)]


def test_snippet_ignores_whitespace() -> None:
    assert snippet_matches("return left + right", "    return left + right")
    assert not snippet_matches("return left * right", "return left + right")


def test_files_in_diff() -> None:
    diff = """diff --git a/calc.py b/calc.py
--- a/calc.py
+++ b/calc.py
@@ -1 +1 @@
-return left + right
+return left * right
"""
    assert files_in_diff(diff) == ["calc.py"]
