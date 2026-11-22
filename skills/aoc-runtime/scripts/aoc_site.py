"""Strict authenticated AoC parsing. Absence of evidence is never unsolved."""
from html.parser import HTMLParser
import re
import time
import urllib.error
import urllib.request

from common import Blocked, digest, now, finale
from api import NoRedirect


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.user = None
        self.articles, self.codes = [], []
        self.depth = self.article_depth = self.user_depth = 0
        self.article = []
        self.user_text = []
        self.code = None
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag not in ("br", "hr", "img", "input", "meta", "link"):
            self.depth += 1
        if tag == "div" and "user" in attrs.get("class", "").split():
            self.user_depth = self.depth
        if tag == "article":
            self.article_depth = self.depth
            self.article = []
        if tag == "code":
            self.code = []
        if tag in ("p", "pre", "li", "h2", "br") and self.article_depth:
            self.article.append("\n")

    def handle_endtag(self, tag):
        if tag in ("br", "hr", "img", "input", "meta", "link"):
            return
        if tag == "code" and self.code is not None:
            self.codes.append("".join(self.code))
            self.code = None
        if self.article_depth == self.depth and tag == "article":
            self.articles.append("".join(self.article))
            self.article_depth = 0
        if self.user_depth == self.depth and tag == "div":
            self.user = " ".join("".join(self.user_text).split())
            self.user_depth = 0
        self.depth = max(0, self.depth - 1)

    def handle_data(self, data):
        self.text.append(data)
        if self.user_depth and self.depth == self.user_depth:
            self.user_text.append(data)
        if self.article_depth:
            self.article.append(data)
        if self.code is not None:
            self.code.append(data)


class Site:
    def __init__(self, session, account):
        self.session, self.account = session, account
        self.opener = urllib.request.build_opener(NoRedirect)

    def fetch(self, year, day, suffix="", data=None):
        request = urllib.request.Request(f"https://adventofcode.com/{year}/day/{day}{suffix}",
            data=data, headers={"Cookie": "session=" + self.session,
                "User-Agent": "rolandtritsch/pcc-aoc-solver-scala (personal solver)"})
        # POST is deliberately never retried at the transport layer.
        for attempt in range(3 if data is None else 1):
            try:
                with self.opener.open(request, timeout=20) as response:
                    return response.read(2 * 1024 * 1024).decode("utf-8")
            except Exception as error:
                if isinstance(error, urllib.error.HTTPError) and error.code not in (429, 502, 503, 504):
                    raise Blocked(f"AoC HTTP {error.code}; authentication/resource needs attention") from None
                if data is not None or attempt == 2:
                    raise Blocked("AoC transport failed; submission may be uncertain") from None
                time.sleep(2 ** attempt)

    def page(self, year, day):
        html = self.fetch(year, day)
        return status(html, self.account, day, year)


def status(html, account, day, year=None):
    page = Page(html)
    if not page.user or digest(page.user) != account:
        raise Blocked("AoC authentication/account mismatch")
    if not page.articles or not re.search(rf"--- Day {day}: .+ ---", page.articles[0]):
        raise Blocked("Unrecognized or incomplete puzzle page")
    text = "".join(page.text)
    answers = re.findall(r"Your puzzle answer was\s*<code>(.*?)</code>", html, re.S)
    from html import unescape
    answers = [unescape(re.sub("<[^>]+>", "", a)) for a in answers]
    complete = 2 if "Both parts of this puzzle are complete!" in text else (
        1 if "The first half of this puzzle is complete!" in text else 0)
    if len(answers) < complete and complete:
        # Finales may have no second computational answer.
        if len(answers) != 1 or complete != 2 or year is None or not finale(year, day, 2):
            raise Blocked("Completion marker and accepted-answer evidence disagree")
    if complete == 0 and not ('name="level"' in html or "name='level'" in html):
        raise Blocked("No recognized completion marker or answer form")
    return {"account": account, "complete": complete, "answers": answers,
            "articles": page.articles, "observedAt": now()}


def verdict(html):
    page = Page(html)
    text = " ".join(" ".join(page.articles).split())
    if "That's the right answer!" in text:
        return "accepted", text, None
    if "That's not the right answer" in text:
        return "rejected", text, None
    if "You gave an answer too recently" in text:
        minutes = re.search(r"(\d+)m", text)
        seconds = re.search(r"(\d+)s", text)
        delay = (int(minutes[1]) * 60 if minutes else 0) + (int(seconds[1]) if seconds else 0)
        return "rate_limited", text, delay + 5 if delay else 65
    return "uncertain", text or "Unrecognized submission response", None
