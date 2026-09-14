import urllib.robotparser
from urllib.parse import urlparse

import httpx
import trafilatura

from .base import ExtractedPage


async def extract_url(url: str) -> list[ExtractedPage]:
    parsed_url = urlparse(url)
    robots_url = f"{parsed_url.scheme}://{parsed_url.netloc}/robots.txt"

    rp = urllib.robotparser.RobotFileParser()

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            robots_resp = await client.get(robots_url)
            rp.parse(robots_resp.text.splitlines())
            if not rp.can_fetch("*", url):
                raise PermissionError(f"robots.txt disallows fetching {url}")
    except httpx.RequestError:
        # If robots.txt cannot be fetched, we assume it's allowed
        pass

    # Fetch main content
    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        html = response.text

    # Extract with trafilatura
    extracted = trafilatura.extract(
        html,
        include_tables=True,
        include_formatting=True,
        include_links=True,
        output_format="markdown",
    )

    if not extracted:
        extracted = "No content could be extracted."

    metadata = trafilatura.extract_metadata(html)
    meta_dict = {
        "title": metadata.title if metadata else None,
        "author": metadata.author if metadata else None,
        "canonical_url": metadata.url if metadata else url,
        "publish_date": metadata.date if metadata else None,
    }

    return [
        ExtractedPage(page_number=1, content=extracted, content_type="text", metadata=meta_dict)
    ]
