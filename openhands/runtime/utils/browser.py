import re
from typing import Any


def extract_page_url(browser_content: str) -> str | None | Any:
    # Regex to find the line starting with "- Page URL:" and capture the URL
    # Explanation:
    # ^                - Matches the start of a line (due to re.MULTILINE)
    # \s*              - Matches optional leading whitespace
    # - Page URL:      - Matches the literal string
    # \s+              - Matches one or more whitespace characters after the colon
    # (https?://[^\s]+) - Captures the URL (starts with http/https, followed by non-whitespace chars)
    pattern = re.compile(r'^\s*- Page URL:\s+(https?://[^\s]+)', re.MULTILINE)
    match = pattern.search(browser_content)
    page_url = None
    if match:
        page_url = match.group(1)  # group(1) is the captured URL
    return page_url
