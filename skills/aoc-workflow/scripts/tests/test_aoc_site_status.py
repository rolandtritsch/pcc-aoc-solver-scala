import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "site_status", Path(__file__).parents[1] / "aoc_site_status.py")
site_status = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site_status)


class PartsCompleteTest(unittest.TestCase):
    def test_both_parts_complete(self):
        html = "...Both parts of this puzzle are complete!..."
        self.assertEqual(site_status.parts_complete(html), (True, True))

    def test_only_first_part_complete(self):
        html = "...The first half of this puzzle is complete!..."
        self.assertEqual(site_status.parts_complete(html), (True, False))

    def test_neither_part_complete(self):
        html = "...submit your answer..."
        self.assertEqual(site_status.parts_complete(html), (False, False))


class IsPartCompleteTest(unittest.TestCase):
    def test_part1_reflects_first_half_marker(self):
        fetch = lambda year, day, session: "The first half of this puzzle is complete!"
        self.assertTrue(site_status.is_part_complete(2015, 4, 1, "token", fetch=fetch))
        self.assertFalse(site_status.is_part_complete(2015, 4, 2, "token", fetch=fetch))

    def test_part2_requires_both_complete_marker(self):
        fetch = lambda year, day, session: "Both parts of this puzzle are complete!"
        self.assertTrue(site_status.is_part_complete(2015, 4, 1, "token", fetch=fetch))
        self.assertTrue(site_status.is_part_complete(2015, 4, 2, "token", fetch=fetch))

    def test_neither_marker_is_not_complete(self):
        fetch = lambda year, day, session: "nothing to see here"
        self.assertFalse(site_status.is_part_complete(2015, 4, 1, "token", fetch=fetch))
        self.assertFalse(site_status.is_part_complete(2015, 4, 2, "token", fetch=fetch))

    def test_fetch_receives_year_day_session(self):
        seen = []
        def fetch(year, day, session):
            seen.append((year, day, session))
            return ""
        site_status.is_part_complete(2015, 4, 1, "my-token", fetch=fetch)
        self.assertEqual(seen, [(2015, 4, "my-token")])


class FetchPageTest(unittest.TestCase):
    def test_sends_session_cookie_header(self):
        captured = {}
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *exc): return False
            def read(self, n): return b"ok"
        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["cookie"] = request.get_header("Cookie")
            captured["timeout"] = timeout
            return FakeResponse()
        orig = site_status.urllib.request.urlopen
        site_status.urllib.request.urlopen = fake_urlopen
        try:
            result = site_status.fetch_page(2015, 4, "abc123")
        finally:
            site_status.urllib.request.urlopen = orig
        self.assertEqual(captured["url"], "https://adventofcode.com/2015/day/4")
        self.assertEqual(captured["cookie"], "session=abc123")
        self.assertEqual(result, "ok")


if __name__ == "__main__":
    unittest.main()
