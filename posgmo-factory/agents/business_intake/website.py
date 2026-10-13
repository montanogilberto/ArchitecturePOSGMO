"""
Reads the business owner's website (when they paste its URL) so the analysis
knows more about the business — what it sells, how it works — without asking.

Safety: this fetches a URL typed by a website visitor, so it only allows
http/https on ports 80/443, refuses any host that resolves to a private,
loopback or link-local address (checked again on every redirect), caps time
and size, and keeps text only. The page is untrusted: the analyst prompt
treats it as information about the business, never as instructions.
Residual risk: DNS can change between the check and the request (rebinding);
acceptable for read-only GETs of public pages, but keep this service off any
network with sensitive internal HTTP endpoints.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

MAX_BYTES = 1_500_000
MAX_TEXT_CHARS = 4000
MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 8
_SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "iframe"}


class WebsiteError(ValueError):
    """The URL is not allowed or the page could not be read."""


def check_url(url: str) -> str:
    """Returns the URL if it is a public http(s) address, else raises WebsiteError."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise WebsiteError("Only http:// or https:// website addresses are supported.")
    if parts.port not in (None, 80, 443):
        raise WebsiteError("Only standard web ports are supported.")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror:
        raise WebsiteError("That website address could not be found.")
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise WebsiteError("That address is not a public website.")
    return url.strip()


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.parts: list[str] = []
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            a = {k.lower(): (v or "") for k, v in attrs}
            if a.get("name", "").lower() in ("description", "og:description") or a.get("property", "").lower() == "og:description":
                self.description = self.description or a.get("content", "")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
        elif data.strip():
            self.parts.append(data.strip())


def extract_text(html: str) -> dict:
    parser = _TextExtractor()
    parser.feed(html)
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    return {
        "title": re.sub(r"\s+", " ", parser.title).strip()[:200],
        "description": parser.description.strip()[:500],
        "text": text[:MAX_TEXT_CHARS],
    }


def fetch_website(url: str) -> dict:
    """Returns {"url", "title", "description", "text"}; raises WebsiteError."""
    current = check_url(url)
    with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False,
                      headers={"User-Agent": "GMO-Factory-BusinessIntake/1.0"}) as client:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                with client.stream("GET", current) as response:
                    if response.is_redirect:
                        current = check_url(urljoin(current, response.headers.get("location", "")))
                        continue
                    if response.status_code >= 400:
                        raise WebsiteError(f"The website answered with an error ({response.status_code}).")
                    if "html" not in response.headers.get("content-type", "html").lower():
                        raise WebsiteError("That address is not a web page.")
                    body = b""
                    for chunk in response.iter_bytes():
                        body += chunk
                        if len(body) > MAX_BYTES:
                            break
                    html = body.decode(response.encoding or "utf-8", errors="replace")
                    return {"url": current, **extract_text(html)}
            except httpx.HTTPError:
                raise WebsiteError("The website could not be reached.")
    raise WebsiteError("The website redirected too many times.")
