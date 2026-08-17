import requests
import pandas as pd
import time
import re

from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse


# ============================================================
# GLOBAL STORAGE
# ============================================================

visited = set()
regulation_rows = []
failed_urls = []


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Chrome/150.0 Safari/537.36"
    )
}


# ============================================================
# 1. PARSE TITLE URL
# ============================================================

def get_title_info(title_url):
    """
    Parse a Cornell title URL.

    Example:
        https://www.law.cornell.edu/regulations/california/title-1

    Returns:
        {
            "state": "california",
            "title_number": "1",
            "hierarchy_prefix": "/regulations/california/title-1",
            "state_prefix": "/regulations/california/"
        }
    """

    path = urlparse(title_url).path.rstrip("/")

    match = re.fullmatch(
        r"/regulations/([^/]+)/title-([^/]+)",
        path
    )

    if not match:
        raise ValueError(
            f"Could not parse Cornell title URL: {title_url}"
        )

    state = match.group(1)
    title_number = match.group(2)

    return {
        "state": state,
        "title_number": title_number,
        "hierarchy_prefix": path,
        "state_prefix": f"/regulations/{state}/"
    }


# ============================================================
# 2. DOWNLOAD PAGE
# ============================================================

# ============================================================
# DOWNLOAD PAGE WITH RETRIES
# ============================================================

def get_soup(
    url,
    max_retries=3,
    retry_delay=2
):
    """
    Download a Cornell page.

    If the request fails, retry several times before
    raising the error.

    Example delays:
        attempt 1 fails -> wait 2 seconds
        attempt 2 fails -> wait 4 seconds
        attempt 3 fails -> give up
    """

    last_error = None

    for attempt in range(
        1,
        max_retries + 1
    ):

        try:

            response = requests.get(
                url,
                headers=HEADERS,
                timeout=30
            )

            response.raise_for_status()

            return BeautifulSoup(
                response.text,
                "html.parser"
            )

        except requests.RequestException as e:

            last_error = e

            print(
                f"Request failed "
                f"(attempt {attempt}/{max_retries}): "
                f"{e}"
            )

            if attempt < max_retries:

                wait_time = (
                    retry_delay * attempt
                )

                print(
                    f"Retrying in "
                    f"{wait_time} seconds..."
                )

                time.sleep(wait_time)

    # All attempts failed
    raise last_error


# ============================================================
# 3. CLEAN URL
# ============================================================

def clean_url(url):
    """
    Remove fragments and trailing slashes.
    """

    return url.split("#")[0].rstrip("/")


# ============================================================
# 4. CHECK WHETHER URL IS ON CORNELL
# ============================================================

def is_cornell_url(url):
    """
    Only allow law.cornell.edu.
    """

    parsed = urlparse(url)

    return parsed.netloc in {
        "",
        "www.law.cornell.edu",
        "law.cornell.edu"
    }


# ============================================================
# 5. CHECK WHETHER PAGE IS PART OF TITLE HIERARCHY
# ============================================================

def is_hierarchy_page(url, title_info):
    """
    Returns True if the URL belongs to the hierarchy
    underneath the current title.

    Example:

        /title-1
        /title-1/division-1
        /title-1/division-1/chapter-1
        /title-1/division-1/chapter-1/article-1
    """

    path = urlparse(url).path.rstrip("/")

    hierarchy_prefix = title_info["hierarchy_prefix"]

    return (
        path == hierarchy_prefix
        or path.startswith(
            hierarchy_prefix + "/"
        )
    )


# ============================================================
# 6. IDENTIFY CANDIDATE REGULATION/TEXT PAGE
# ============================================================

def is_regulation_page(url, title_info):
    """
    A candidate regulation page:

    1. Must remain inside the same state's regulations.
    2. Must NOT be a hierarchy page underneath /title-X/.

    This avoids hard-coding things such as:
        1-CCR-
        OAR-
        etc.
    """

    path = urlparse(url).path.rstrip("/")

    state_prefix = title_info["state_prefix"]

    # Must stay inside this state's regulation section
    if not path.startswith(state_prefix):
        return False

    # Title hierarchy pages are not leaf regulation pages
    if is_hierarchy_page(
        url,
        title_info
    ):
        return False

    return True


# ============================================================
# 7. CHECK WHETHER A LINK IS ALLOWED
# ============================================================

def is_allowed_link(url, title_info):
    """
    Determine whether this URL can be considered by the scraper.
    """

    url = clean_url(url)

    if not is_cornell_url(url):
        return False

    path = urlparse(url).path.rstrip("/")

    # Must remain inside the current state's regulations
    if not path.startswith(
        title_info["state_prefix"]
    ):
        return False

    # Allow current title hierarchy
    if is_hierarchy_page(
        url,
        title_info
    ):
        return True

    # Allow potential text/leaf pages
    if is_regulation_page(
        url,
        title_info
    ):
        return True

    return False


# ============================================================
# 8. EXTRACT PAGE TITLE
# ============================================================

def extract_page_title(soup):
    """
    Extract the main H1 from the page.
    """

    h1 = soup.find("h1")

    if h1:
        return h1.get_text(
            " ",
            strip=True
        )

    return ""


# ============================================================
# 9. EXTRACT REGULATION TEXT
# ============================================================

def extract_regulation_text(soup):
    """
    Extract visible text from a regulation page.

    We can make this more precise later once we settle
    on Cornell's content container.
    """

    # Remove obvious junk
    for tag in soup.find_all(
        [
            "script",
            "style",
            "nav",
            "header",
            "footer"
        ]
    ):
        tag.decompose()

    main = soup.find("main")

    if main is None:
        main = soup.body

    if main is None:
        return ""

    text = main.get_text(
        "\n",
        strip=True
    )

    # Collapse excessive blank lines
    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text
    )

    return text.strip()


# ============================================================
# 10. FIND ONLY FORWARD CHILD LINKS
# ============================================================

def get_child_links(
    soup,
    current_url,
    title_info
):
    """
    Get links that move DOWNWARD through the hierarchy.

    Prevents breadcrumb behavior like:

        Article 1
            -> Chapter 1
            -> Division 1
            -> Title 1

    Those are backwards links and should not be followed.
    """

    current_url = clean_url(current_url)

    current_path = urlparse(
        current_url
    ).path.rstrip("/")

    child_links = []

    for a in soup.find_all(
        "a",
        href=True
    ):

        full_url = urljoin(
            current_url,
            a["href"]
        )

        full_url = clean_url(full_url)

        # ----------------------------------------
        # General restrictions
        # ----------------------------------------

        if not is_allowed_link(
            full_url,
            title_info
        ):
            continue

        # Don't process current page
        if full_url == current_url:
            continue

        candidate_path = urlparse(
            full_url
        ).path.rstrip("/")

        # ========================================
        # CASE 1:
        # Candidate regulation/text page
        # ========================================

        if is_regulation_page(
            full_url,
            title_info
        ):

            if full_url not in child_links:
                child_links.append(full_url)

            continue

        # ========================================
        # CASE 2:
        # Hierarchy page
        #
        # Must be BELOW current URL
        # and only one hierarchy level deeper.
        # ========================================

        prefix = current_path + "/"

        if not candidate_path.startswith(
            prefix
        ):
            continue

        remainder = candidate_path[
            len(prefix):
        ]

        # Don't jump multiple levels
        if "/" in remainder:
            continue

        if full_url not in child_links:
            child_links.append(full_url)

    return child_links


# ============================================================
# 11. RECURSIVE DEPTH-FIRST SCRAPER
# ============================================================

def scrape_title_page(
    url,
    title_info,
    hierarchy=None,
    depth=0,
    delay=0.4
):
    """
    Recursively scrape one Cornell title.

    Important behavior:

    - successful URLs go into `visited`
    - failed URLs go into `failed_urls`
    - failed URLs are NOT marked as visited
    - temporary connection failures are retried by get_soup()
    """

    global visited
    global regulation_rows
    global failed_urls

    if hierarchy is None:
        hierarchy = []

    url = clean_url(url)

    # --------------------------------------------
    # Already successfully processed
    # --------------------------------------------

    if url in visited:

        print(
            "  " * depth +
            f"Already visited: {url}"
        )

        return

    # --------------------------------------------
    # Safety check
    # --------------------------------------------

    if not is_allowed_link(
        url,
        title_info
    ):

        print(
            "  " * depth +
            f"Skipping disallowed URL: {url}"
        )

        return

    print(
        "  " * depth +
        f"Opening: {url}"
    )

    # --------------------------------------------
    # Download page
    # --------------------------------------------

    try:

        soup = get_soup(url)

    except Exception as e:

        print(
            "  " * depth +
            f"FAILED AFTER RETRIES: {e}"
        )

        failed_urls.append({
            "state": title_info["state"],
            "title": title_info["title_number"],
            "hierarchy": " > ".join(hierarchy),
            "url": url,
            "error": str(e)
        })

        # IMPORTANT:
        # Do NOT add failed URL to visited
        return

    # --------------------------------------------
    # Page successfully downloaded
    # --------------------------------------------

    visited.add(url)

    # --------------------------------------------
    # Extract title
    # --------------------------------------------

    page_title = extract_page_title(
        soup
    )

    if page_title:

        current_hierarchy = (
            hierarchy + [page_title]
        )

    else:

        current_hierarchy = (
            hierarchy.copy()
        )

    # ============================================
    # BASE CASE:
    # Regulation/text page
    # ============================================

    if is_regulation_page(
        url,
        title_info
    ):

        try:

            text = extract_regulation_text(
                soup
            )

            regulation_rows.append({
                "state": title_info["state"],
                "title": title_info["title_number"],
                "hierarchy": " > ".join(
                    current_hierarchy
                ),
                "name": page_title,
                "text": text,
                "url": url
            })

            print(
                "  " * depth +
                "✓ Saved regulation text"
            )

        except Exception as e:

            print(
                "  " * depth +
                f"ERROR extracting text: {e}"
            )

            failed_urls.append({
                "state": title_info["state"],
                "title": title_info["title_number"],
                "hierarchy": " > ".join(
                    current_hierarchy
                ),
                "url": url,
                "error": (
                    "Text extraction error: "
                    + str(e)
                )
            })

        return

    # ============================================
    # RECURSIVE CASE:
    # Hierarchy page
    # ============================================

    try:

        child_links = get_child_links(
            soup=soup,
            current_url=url,
            title_info=title_info
        )

    except Exception as e:

        print(
            "  " * depth +
            f"ERROR finding child links: {e}"
        )

        failed_urls.append({
            "state": title_info["state"],
            "title": title_info["title_number"],
            "hierarchy": " > ".join(
                current_hierarchy
            ),
            "url": url,
            "error": (
                "Child-link extraction error: "
                + str(e)
            )
        })

        return

    print(
        "  " * depth +
        f"Found {len(child_links)} child links"
    )

    # --------------------------------------------
    # Depth-first recursion
    # --------------------------------------------

    for child_url in child_links:

        scrape_title_page(
            url=child_url,
            title_info=title_info,
            hierarchy=current_hierarchy,
            depth=depth + 1,
            delay=delay
        )

        time.sleep(delay)


# ============================================================
# 12. WRAPPER FUNCTION FOR ONE TITLE
# ============================================================

# ============================================================
# SCRAPE ONE TITLE
# ============================================================

def scrape_cornell_title(
    title_url,
    output_csv=None,
    failed_csv=None,
    delay=0.4
):
    """
    Scrape one Cornell title.

    Returns:
        df
        failed_df
    """

    global visited
    global regulation_rows
    global failed_urls

    # Fresh storage for this title
    visited = set()
    regulation_rows = []
    failed_urls = []

    title_url = clean_url(
        title_url
    )

    title_info = get_title_info(
        title_url
    )

    print("=" * 80)

    print(
        f"Starting {title_info['state']} "
        f"Title {title_info['title_number']}"
    )

    print("=" * 80)

    # --------------------------------------------
    # Run recursive scraper
    # --------------------------------------------

    scrape_title_page(
        url=title_url,
        title_info=title_info,
        hierarchy=[],
        depth=0,
        delay=delay
    )

    # --------------------------------------------
    # Create DataFrames
    # --------------------------------------------

    df = pd.DataFrame(
        regulation_rows
    )

    failed_df = pd.DataFrame(
        failed_urls
    )

    # --------------------------------------------
    # Save successful regulations
    # --------------------------------------------

    if output_csv is not None:

        df.to_csv(
            output_csv,
            index=False,
            encoding="utf-8"
        )

        print(
            f"Saved regulations to: "
            f"{output_csv}"
        )

    # --------------------------------------------
    # Save failures
    # --------------------------------------------

    if failed_csv is not None:

        failed_df.to_csv(
            failed_csv,
            index=False,
            encoding="utf-8"
        )

        print(
            f"Saved failed URLs to: "
            f"{failed_csv}"
        )

    # --------------------------------------------
    # Summary
    # --------------------------------------------

    print()
    print("=" * 80)
    print("TITLE SCRAPE COMPLETE")
    print("=" * 80)

    print(
        "Pages successfully visited:",
        len(visited)
    )

    print(
        "Regulations saved:",
        len(df)
    )

    print(
        "Failed URLs:",
        len(failed_df)
    )

    return df, failed_df


# ============================================================
# 13. GET TITLE LINKS FROM A STATE HOMEPAGE
# ============================================================

def get_state_title_links(state_url):
    """
    Given a Cornell state regulations homepage, return all
    title links listed for that state.

    Example:
        https://www.law.cornell.edu/regulations/california

    Returns something like:

        [
            {
                "title_name": "Title 1 - General Provisions",
                "url": "https://www.law.cornell.edu/regulations/california/title-1"
            },
            {
                "title_name": "Title 2 - Administration",
                "url": "https://www.law.cornell.edu/regulations/california/title-2"
            },
            ...
        ]
    """

    state_url = clean_url(state_url)

    parsed = urlparse(state_url)
    state_path = parsed.path.rstrip("/")

    soup = get_soup(state_url)

    title_links = []

    for a in soup.find_all("a", href=True):

        text = a.get_text(" ", strip=True)

        full_url = urljoin(
            state_url,
            a["href"]
        )

        full_url = clean_url(full_url)

        path = urlparse(full_url).path.rstrip("/")

        # Only allow links immediately under this state's
        # regulations page that look like /title-X
        pattern = re.escape(state_path) + r"/title-[^/]+"

        if not re.fullmatch(pattern, path):
            continue

        if not text.lower().startswith("title"):
            continue

        if full_url not in [
            x["url"] for x in title_links
        ]:
            title_links.append({
                "title_name": text,
                "url": full_url
            })

    return title_links

# ============================================================
# 14. SCRAPE AN ENTIRE STATE
# ============================================================

def scrape_cornell_state(
    state_url,
    output_csv=None,
    failed_csv=None,
    delay=0.4
):
    """
    Scrape every title found on a Cornell state
    regulations homepage.

    Saves:
        successful regulation rows
        failed URLs

    Returns:
        state_df
        state_failed_df
    """

    state_url = clean_url(
        state_url
    )

    print("=" * 80)
    print(f"STATE PAGE: {state_url}")
    print("=" * 80)

    # --------------------------------------------
    # Discover titles
    # --------------------------------------------

    title_links = get_state_title_links(
        state_url
    )

    print(
        f"\nFound {len(title_links)} titles.\n"
    )

    for item in title_links:

        print(
            item["title_name"],
            "->",
            item["url"]
        )

    # --------------------------------------------
    # Storage
    # --------------------------------------------

    all_title_dfs = []
    all_failed_dfs = []

    # --------------------------------------------
    # Scrape titles one at a time
    # --------------------------------------------

    for i, item in enumerate(
        title_links,
        start=1
    ):

        print()
        print("#" * 80)

        print(
            f"TITLE {i} OF "
            f"{len(title_links)}"
        )

        print(
            item["title_name"]
        )

        print(
            item["url"]
        )

        print("#" * 80)

        try:

            title_df, title_failed_df = (
                scrape_cornell_title(
                    title_url=item["url"],
                    output_csv=None,
                    failed_csv=None,
                    delay=delay
                )
            )

            # Human-readable title
            if not title_df.empty:

                title_df[
                    "title_name"
                ] = item["title_name"]

                all_title_dfs.append(
                    title_df
                )

            # Failed URLs
            if not title_failed_df.empty:

                title_failed_df[
                    "title_name"
                ] = item["title_name"]

                all_failed_dfs.append(
                    title_failed_df
                )

            print(
                f"✓ Finished "
                f"{item['title_name']}"
            )

            print(
                f"  Regulations: "
                f"{len(title_df)}"
            )

            print(
                f"  Failed URLs: "
                f"{len(title_failed_df)}"
            )

        except Exception as e:

            print(
                f"✗ TITLE-LEVEL ERROR: "
                f"{item['title_name']}: {e}"
            )

            all_failed_dfs.append(
                pd.DataFrame([
                    {
                        "state": urlparse(
                            state_url
                        ).path.split("/")[-1],
                        "title": None,
                        "hierarchy": "",
                        "url": item["url"],
                        "error": (
                            "Title-level error: "
                            + str(e)
                        ),
                        "title_name": (
                            item["title_name"]
                        )
                    }
                ])
            )

        time.sleep(delay)

    # --------------------------------------------
    # Combine successful data
    # --------------------------------------------

    if all_title_dfs:

        state_df = pd.concat(
            all_title_dfs,
            ignore_index=True
        )

    else:

        state_df = pd.DataFrame()

    # --------------------------------------------
    # Combine failure data
    # --------------------------------------------

    if all_failed_dfs:

        state_failed_df = pd.concat(
            all_failed_dfs,
            ignore_index=True
        )

    else:

        state_failed_df = pd.DataFrame()

    # --------------------------------------------
    # Save successful data
    # --------------------------------------------

    if output_csv is not None:

        state_df.to_csv(
            output_csv,
            index=False,
            encoding="utf-8"
        )

        print(
            f"\nSaved state regulations to:"
        )

        print(output_csv)

    # --------------------------------------------
    # Save failed URLs
    # --------------------------------------------

    if failed_csv is not None:

        state_failed_df.to_csv(
            failed_csv,
            index=False,
            encoding="utf-8"
        )

        print(
            f"\nSaved failed URLs to:"
        )

        print(failed_csv)

    # --------------------------------------------
    # Final summary
    # --------------------------------------------

    print()
    print("=" * 80)
    print("STATE SCRAPE COMPLETE")
    print("=" * 80)

    print(
        "Total regulations:",
        len(state_df)
    )

    print(
        "Total failed URLs:",
        len(state_failed_df)
    )

    return state_df, state_failed_df