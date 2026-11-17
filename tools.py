
import os
import requests

from urllib.parse import urlparse
from bs4 import BeautifulSoup
from tavily import TavilyClient
from langchain.tools import tool
from dotenv import load_dotenv


# --------------------------------------------------
# ENVIRONMENT CONFIGURATION
# --------------------------------------------------

load_dotenv()

api_key = os.getenv("TAVILY_API_KEY")

if not api_key:
    raise ValueError(
        "TAVILY_API_KEY is missing from your .env file."
    )

tavily = TavilyClient(api_key=api_key)


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

MAX_SEARCH_RESULTS = 5
MAX_SCRAPED_CHARACTERS = 6000
REQUEST_TIMEOUT = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# --------------------------------------------------
# TOOL 1: WEB SEARCH
# --------------------------------------------------

@tool
def web_search(query: str) -> str:
    """
    Search the web using Tavily.

    Returns source titles, URLs, and detailed snippets.
    """

    try:
        if not query or not query.strip():
            return "Search failed: Please provide a search query."

        results = tavily.search(
            query=query.strip(),
            max_results=MAX_SEARCH_RESULTS,
            search_depth="advanced",
        )

        search_results = results.get("results", [])

        if not search_results:
            return "No search results were found."

        output = []

        for index, result in enumerate(search_results, start=1):

            title = result.get("title") or "Untitled"
            url = result.get("url") or "No URL available"
            content = result.get("content") or "No snippet available"

            output.append(
                f"RESULT {index}\n"
                f"Title: {title}\n"
                f"URL: {url}\n"
                f"Snippet:\n{content[:1200]}\n"
            )

        formatted_results = (
            "\n\n" + ("\n" + "=" * 70 + "\n").join(output)
        )

        return formatted_results

    except Exception as exc:
        return (
            f"Web search failed: {type(exc).__name__}: {exc}"
        )


# --------------------------------------------------
# HELPER: VALIDATE URL
# --------------------------------------------------

def validate_url(url: str) -> bool:
    """Check whether a URL is a valid HTTP or HTTPS URL."""

    try:
        parsed = urlparse(url.strip())

        return (
            parsed.scheme in ("http", "https")
            and bool(parsed.netloc)
            and not parsed.username
            and not parsed.password
        )

    except Exception:
        return False


# --------------------------------------------------
# TOOL 2: WEBPAGE SCRAPING
# --------------------------------------------------

@tool
def scrape_url(url: str) -> str:
    """
    Fetch a webpage and extract readable text.

    Removes navigation, scripts, styles, and other
    unnecessary webpage elements.
    """

    try:
        # Validate URL
        if not url or not url.strip():
            return "Scraping failed: URL is empty."

        url = url.strip()

        if not validate_url(url):
            return f"Scraping failed: Invalid URL: {url}"

        # Fetch webpage
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers=HEADERS,
            allow_redirects=True,
        )

        response.raise_for_status()

        # Check response content type
        content_type = response.headers.get(
            "Content-Type", ""
        ).lower()

        if "html" not in content_type:
            return (
                "Could not read webpage. "
                f"Expected HTML but received: {content_type}"
            )

        # Parse HTML
        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        # Remove unnecessary elements
        unwanted_tags = [
            "script",
            "style",
            "nav",
            "footer",
            "header",
            "aside",
            "form",
            "noscript",
            "iframe",
            "svg",
            "button",
        ]

        for tag in soup(unwanted_tags):
            tag.decompose()

        # Extract page title
        page_title = (
            soup.title.get_text(strip=True)
            if soup.title
            else "Untitled webpage"
        )

        # Prefer main article content
        article = (
            soup.find("article")
            or soup.find("main")
            or soup.body
        )

        if article is None:
            return (
                "Could not extract readable content "
                "from this webpage."
            )

        # Extract readable text
        text = article.get_text(
            separator=" ",
            strip=True,
        )

        # Clean extra whitespace
        text = " ".join(text.split())

        if not text:
            return (
                "The webpage did not contain readable text."
            )

        # Limit extracted content
        text = text[:MAX_SCRAPED_CHARACTERS]

        return (
            f"PAGE TITLE: {page_title}\n"
            f"SOURCE URL: {response.url}\n\n"
            f"WEBPAGE CONTENT:\n{text}"
        )

    except requests.exceptions.Timeout:
        return (
            f"Scraping failed: Website timed out after "
            f"{REQUEST_TIMEOUT} seconds."
        )

    except requests.exceptions.HTTPError as exc:
        return (
            f"Scraping failed: HTTP error: {exc}"
        )

    except requests.exceptions.ConnectionError:
        return (
            "Scraping failed: Could not connect to the website."
        )

    except requests.exceptions.RequestException as exc:
        return (
            f"Scraping failed: {type(exc).__name__}: {exc}"
        )

    except Exception as exc:
        return (
            f"Scraping failed: {type(exc).__name__}: {exc}"
        )
