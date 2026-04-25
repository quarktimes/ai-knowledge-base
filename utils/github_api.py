"""GitHub API utilities for fetching repository information."""

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


def get_repo_info(repo: str, token: Optional[str] = None) -> Optional[dict]:
    """Fetch basic information for a GitHub repository.

    Args:
        repo: Repository in "owner/repo" format, e.g. "torvalds/linux".
        token: Optional GitHub personal access token for higher rate limits.

    Returns:
        A dict with keys (name, full_name, description, stars, forks, url),
        or None if the request fails.

    Raises:
        ValueError: If repo format is invalid.
    """
    if "/" not in repo or repo.count("/") != 1:
        raise ValueError(f'Invalid repo format "{repo}", expected "owner/repo"')

    url = f"{GITHUB_API_BASE}/repos/{repo}"
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    logger.info("Fetching repo info: %s", repo)
    resp = requests.get(url, headers=headers, timeout=10)

    if resp.status_code == 403:
        logger.warning("Rate limited fetching %s: %s", repo, resp.json().get("message"))
        return None
    if resp.status_code == 404:
        logger.warning("Repository not found: %s", repo)
        return None
    if resp.status_code != 200:
        logger.error("Unexpected status %d for %s", resp.status_code, repo)
        return None

    data = resp.json()
    return {
        "name": data["name"],
        "full_name": data["full_name"],
        "description": data.get("description"),
        "stars": data["stargazers_count"],
        "forks": data["forks_count"],
        "url": data["html_url"],
    }
