#!/usr/bin/env python3

"""
Primitive Recursive Web Crawler / Downloader

Version:
    1.0 (Initial Design)

Target:
    Python 3.14+

Author:
    TBD
"""

# --------------------------- #
# Chunk # 1 :: Imports :: BGN #
# --------------------------- #

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# --------------------------- #
# Chunk # 1 :: Imports :: END #
# --------------------------- #


# --------------------------- #
# Chunk # 2 :: Imports :: BGN #
# --------------------------- #

from collections import deque
from urllib.parse import (
    urljoin,
    urlparse,
    urldefrag
)
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

# --------------------------- #
# Chunk # 2 :: Imports :: END #
# --------------------------- #


# --------------------------- #
# Chunk # 3 :: Imports :: BGN #
# --------------------------- #

import time

# --------------------------- #
# Chunk # 3 :: Imports :: END #
# --------------------------- #


# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

DEFAULT_SEARCH_TAGS = ["a", "img", "link"]

DEFAULT_REQUEST_TIMEOUT = 30

DEFAULT_MAX_URLS_VISITED = 1000

VALID_ACTIONS = {
    "DOWNLOAD",
    "RECURSE"
}

# ---------------------------------------------------------------------------
# DATA CLASSES
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class CrawlLevelConfig:
    """
    Configuration for one recursion level.
    """

    regex: list[str]

    compiled_regex: list[re.Pattern] = field(
        default_factory=list
    )

    file_types: list[str] = field(default_factory=list)

    actions: list[str] = field(default_factory=list)

    output_prefix: str = ""

    output_postfix: str = ""


@dataclass(slots=True)
class CrawlConfig:
    """
    Top-level crawl configuration.
    """

    levels: dict[int, CrawlLevelConfig]


@dataclass(slots=True)
class CliArgs:

    base_url: str

    crawl_config: str

    output_base_dir: Path

    max_rec_lvl: int

    search_in_tag_set: list[str]

    crawl_same_domain: bool

    crawl_sub_domains: bool

    respect_robots: bool

    url_white_list: list[str]

    url_black_list: list[str]

    sort_match_asc_by_filename: bool

    expect_output_base_dir_to_exist: bool

    expect_output_base_dir_to_be_empty: bool

    create_sub_dir_in_output_base_dir: bool

    request_timeout: int

    max_urls_visited: int

    debug: bool

    dry_run: bool

    log_file: str | None


@dataclass(slots=True)
class RuntimeConfig:

    cli_args: CliArgs

    crawl_config: CrawlConfig

    effective_output_dir: Path


@dataclass(slots=True)
class CrawlStats:

    urls_visited: int = 0

    urls_skipped: int = 0

    urls_rejected_whitelist: int = 0

    urls_rejected_blacklist: int = 0

    matches_found: int = 0

    files_expected: int = 0

    files_downloaded: int = 0

    files_failed: int = 0

    elapsed_seconds: float = 0.0


# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------

def configure_logging(
    debug_enabled: bool,
    log_file: str | None
) -> None:

    log_level = logging.DEBUG if debug_enabled else logging.INFO

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(message)s"
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root_logger.addHandler(console_handler)

    if log_file:

        file_handler = logging.FileHandler(
            log_file,
            encoding="utf-8"
        )

        file_handler.setFormatter(formatter)

        root_logger.addHandler(file_handler)


# ---------------------------------------------------------------------------
# BOOLEAN PARSER
# ---------------------------------------------------------------------------

def parse_bool(value: str) -> bool:

    normalized = value.strip().lower()

    if normalized in (
        "true",
        "1",
        "yes",
        "y"
    ):
        return True

    if normalized in (
        "false",
        "0",
        "no",
        "n"
    ):
        return False

    raise argparse.ArgumentTypeError(
        f"Invalid boolean value: {value}"
    )


# ---------------------------------------------------------------------------
# LIST PARSER
# ---------------------------------------------------------------------------

def parse_csv_list(value: str) -> list[str]:

    if not value:
        return []

    return [
        item.strip()
        for item in value.split(",")
        if item.strip()
    ]


# ---------------------------------------------------------------------------
# URL VALIDATION
# ---------------------------------------------------------------------------

def validate_url(url: str) -> None:

    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"Unsupported URL scheme: {url}"
        )

    if not parsed.netloc:
        raise ValueError(
            f"Invalid URL: {url}"
        )


# ---------------------------------------------------------------------------
# CONFIG LOADING
# ---------------------------------------------------------------------------

def load_json_from_file(
    file_path: Path
) -> dict[str, Any]:

    with file_path.open(
        mode="r",
        encoding="utf-8"
    ) as fp:

        return json.load(fp)


def load_json_inline(
    raw_json: str
) -> dict[str, Any]:

    return json.loads(raw_json)


def load_config_source(
    config_value: str
) -> dict[str, Any]:

    possible_file = Path(config_value)

    if possible_file.is_file():

        logging.info(
            "Loading crawl config from file: %s",
            possible_file
        )

        return load_json_from_file(
            possible_file
        )

    logging.info(
        "Attempting inline JSON crawl config."
    )

    return load_json_inline(
        config_value
    )


# ---------------------------------------------------------------------------
# CONFIG VALIDATION
# ---------------------------------------------------------------------------

def validate_level_config(
    level: int,
    level_data: dict[str, Any]
) -> CrawlLevelConfig:

    regex = level_data.get("regex", [])

    if not isinstance(regex, list):
        raise ValueError(
            f"Level={level}: regex must be list"
        )

    compiled_regex = []

    for patt in regex:

        try:

            compiled_regex.append(
                re.compile(
                    patt,
                    flags=re.IGNORECASE
                )
            )

        except re.error as exc:

            raise ValueError(
                f"Level={level}: invalid regex={patt}"
            ) from exc

    file_types = level_data.get(
        "fileTypes",
        []
    )

    actions = level_data.get(
        "actions",
        []
    )

    for action in actions:

        if action not in VALID_ACTIONS:

            raise ValueError(
                f"Level={level}: invalid action={action}"
            )

    output_prefix = level_data.get(
        "outputPrefix",
        ""
    )

    output_postfix = level_data.get(
        "outputPostfix",
        ""
    )

    return CrawlLevelConfig(
        regex=regex,
        compiled_regex=compiled_regex,
        file_types=file_types,
        actions=actions,
        output_prefix=output_prefix,
        output_postfix=output_postfix
    )


def build_crawl_config(
    raw_config: dict[str, Any]
) -> CrawlConfig:

    if "levels" not in raw_config:

        raise ValueError(
            "crawlConfig missing 'levels' section"
        )

    levels_raw = raw_config["levels"]

    levels: dict[int, CrawlLevelConfig] = {}

    for key, value in levels_raw.items():

        level_number = int(key)

        levels[level_number] = (
            validate_level_config(
                level_number,
                value
            )
        )

    return CrawlConfig(
        levels=levels
    )

def validate_level_coverage(
    crawl_config: CrawlConfig,
    max_rec_lvl: int
) -> None:

    missing_levels = []

    for level in range(
        max_rec_lvl + 1
    ):

        if (
            level
            not in
            crawl_config.levels
        ):
            missing_levels.append(
                level
            )

    if missing_levels:

        raise ValueError(
            "crawlConfig missing level definitions: "
            + ", ".join(
                map(
                    str,
                    missing_levels
                )
            )
        )

# ---------------------------------------------------------------------------
# OUTPUT DIRECTORY
# ---------------------------------------------------------------------------

def build_effective_output_directory(
    output_base_dir: Path,
    create_sub_dir: bool
) -> Path:

    if not create_sub_dir:
        return output_base_dir

    timestamp = datetime.now().astimezone()

    subdir_name = timestamp.strftime(
        "%Y-%m-%d_%H-%M-%S"
    )

    subdir_name += (
        f"-{timestamp.microsecond // 1000:03d}"
    )

    tz_name = (
        timestamp.tzname() or "UNK"
    )

    subdir_name += (
        f"_{tz_name}"
    )

    return output_base_dir / subdir_name


def validate_output_directory(
    args: CliArgs
) -> Path:

    base_dir = args.output_base_dir

    #
    # Validate BASE directory first
    #

    if args.expect_output_base_dir_to_exist:

        if not base_dir.exists():

            raise ValueError(
                f"Output base directory does not exist: "
                f"{base_dir}"
            )

    else:

        if not base_dir.exists():

            logging.warning(
                "Creating output base directory: %s",
                base_dir
            )

            base_dir.mkdir(
                parents=True,
                exist_ok=True
            )

    #
    # Optional empty check applies to BASE directory
    #

    if (
        args.expect_output_base_dir_to_be_empty
        and
        base_dir.exists()
    ):

        if any(base_dir.iterdir()):

            raise ValueError(
                f"Output base directory is not empty: "
                f"{base_dir}"
            )

    #
    # Now build effective output directory
    #

    output_dir = build_effective_output_directory(
        base_dir,
        args.create_sub_dir_in_output_base_dir
    )

    if not output_dir.exists():

        output_dir.mkdir(
            parents=True,
            exist_ok=True
        )

    return output_dir


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_argument_parser(
) -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(
        description=(
            "Primitive Recursive Web "
            "Crawler / Downloader"
        )
    )

    parser.add_argument(
        "-u",
        "--baseUrl",
        required=True
    )

    parser.add_argument(
        "-cc",
        "--crawlConfig",
        required=True
    )

    parser.add_argument(
        "-o",
        "--outputBaseDir",
        required=True
    )

    parser.add_argument(
        "-r",
        "--maxRecLvl",
        type=int,
        default=0
    )

    parser.add_argument(
        "--searchInTagSet",
        default="a,img,link"
    )

    parser.add_argument(
        "--crawlSameDomain",
        type=parse_bool,
        default=True
    )

    parser.add_argument(
        "--crawlSubDomains",
        type=parse_bool,
        default=True
    )

    parser.add_argument(
        "--respectRobots",
        type=parse_bool,
        default=False
    )

    parser.add_argument(
        "--urlWhiteList",
        default=""
    )

    parser.add_argument(
        "--urlBlackList",
        default=""
    )

    parser.add_argument(
        "--sortMatchAscByFilename",
        type=parse_bool,
        default=False
    )

    parser.add_argument(
        "--expectOutputBaseDirToExist",
        type=parse_bool,
        default=False
    )

    parser.add_argument(
        "--expectOutputBaseDirToBeEmpty",
        type=parse_bool,
        default=False
    )

    parser.add_argument(
        "--createSubDirInOutputBaseDir",
        type=parse_bool,
        default=False
    )

    parser.add_argument(
        "--requestTimeout",
        type=int,
        default=DEFAULT_REQUEST_TIMEOUT
    )

    parser.add_argument(
        "--maxUrlsVisited",
        type=int,
        default=DEFAULT_MAX_URLS_VISITED
    )

    parser.add_argument(
        "-d",
        "--debug",
        action="store_true"
    )

    parser.add_argument(
        "-n",
        "--dryRun",
        action="store_true"
    )

    parser.add_argument(
        "--logFile"
    )

    return parser


# ---------------------------------------------------------------------------
# CLI -> OBJECT
# ---------------------------------------------------------------------------

def parse_cli_args() -> CliArgs:

    parser = build_argument_parser()

    ns = parser.parse_args()

    return CliArgs(
        base_url=ns.baseUrl,
        crawl_config=ns.crawlConfig,
        output_base_dir=Path(
            ns.outputBaseDir
        ),

        max_rec_lvl=ns.maxRecLvl,

        search_in_tag_set=parse_csv_list(
            ns.searchInTagSet
        ),

        crawl_same_domain=ns.crawlSameDomain,

        crawl_sub_domains=ns.crawlSubDomains,

        respect_robots=ns.respectRobots,

        url_white_list=parse_csv_list(
            ns.urlWhiteList
        ),

        url_black_list=parse_csv_list(
            ns.urlBlackList
        ),

        sort_match_asc_by_filename=(
            ns.sortMatchAscByFilename
        ),

        expect_output_base_dir_to_exist=(
            ns.expectOutputBaseDirToExist
        ),

        expect_output_base_dir_to_be_empty=(
            ns.expectOutputBaseDirToBeEmpty
        ),

        create_sub_dir_in_output_base_dir=(
            ns.createSubDirInOutputBaseDir
        ),

        request_timeout=ns.requestTimeout,

        max_urls_visited=ns.maxUrlsVisited,

        debug=ns.debug,

        dry_run=ns.dryRun,

        log_file=ns.logFile
    )


# ---------------------------------------------------------------------------
# RUNTIME CONFIG
# ---------------------------------------------------------------------------

def build_runtime_config(
    cli_args: CliArgs
) -> RuntimeConfig:

    validate_url(
        cli_args.base_url
    )

    raw_config = load_config_source(
        cli_args.crawl_config
    )

    crawl_config = build_crawl_config(
        raw_config
    )
    
    validate_level_coverage(
        crawl_config,
        cli_args.max_rec_lvl
    )

    effective_output_dir = (
        validate_output_directory(
            cli_args
        )
    )

    return RuntimeConfig(
        cli_args=cli_args,
        crawl_config=crawl_config,
        effective_output_dir=effective_output_dir
    )

# ---------------------------------------------------------------------------
# END OF CHUNK #1
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# HTTP SESSION
# ---------------------------------------------------------------------------

def create_http_session() -> requests.Session:

    session = requests.Session()

    session.headers.update(
        {
            "User-Agent":
                "PrimitiveCrawler/1.0"
        }
    )

    return session


# ---------------------------------------------------------------------------
# ROBOTS CACHE
# ---------------------------------------------------------------------------

ROBOTS_CACHE: dict[str, RobotFileParser] = {}


def can_fetch_url(
    runtime: RuntimeConfig,
    session: requests.Session,
    url: str
) -> bool:

    if not runtime.cli_args.respect_robots:
        return True

    parsed = urlparse(url)

    robots_url = (
        f"{parsed.scheme}://"
        f"{parsed.netloc}/robots.txt"
    )

    if robots_url not in ROBOTS_CACHE:

        parser = RobotFileParser()

        parser.set_url(
            robots_url
        )

        try:

            parser.read()

        except Exception:

            logging.warning(
                "Unable to read robots.txt: %s",
                robots_url
            )

            return True

        ROBOTS_CACHE[
            robots_url
        ] = parser

    parser = ROBOTS_CACHE[
        robots_url
    ]

    return parser.can_fetch(
        "*",
        url
    )


# ---------------------------------------------------------------------------
# URL NORMALIZATION
# ---------------------------------------------------------------------------

def is_supported_url(
    url: str
) -> bool:

    try:
        parsed = urlparse(url)

        return (
            parsed.scheme.lower()
            in
            ("http", "https")
        )

    except Exception:
        return False

def normalize_url(
    base_url: str,
    discovered_url: str
) -> str:

    absolute_url = urljoin(
        base_url,
        discovered_url
    )

    absolute_url, _ = urldefrag(
        absolute_url
    )

    return absolute_url.strip()


# ---------------------------------------------------------------------------
# DOMAIN UTILITIES
# ---------------------------------------------------------------------------

def extract_root_domain(
    hostname: str
) -> str:

    hostname = hostname.lower()

    parts = hostname.split(".")

    if len(parts) < 2:
        return hostname

    return ".".join(parts[-2:])


def url_allowed_by_domain_rules(
    runtime: RuntimeConfig,
    candidate_url: str
) -> bool:

    cli = runtime.cli_args

    if not cli.crawl_same_domain:
        return True

    seed_host = (
        urlparse(
            cli.base_url
        ).hostname or ""
    )

    candidate_host = (
        urlparse(
            candidate_url
        ).hostname or ""
    )

    seed_root = extract_root_domain(
        seed_host
    )

    candidate_root = extract_root_domain(
        candidate_host
    )

    if seed_root != candidate_root:
        return False

    if cli.crawl_sub_domains:
        return True

    return (
        seed_host.lower()
        ==
        candidate_host.lower()
    )


# ---------------------------------------------------------------------------
# WHITELIST / BLACKLIST
# ---------------------------------------------------------------------------

def matches_any_regex(
    value: str,
    patterns: list[str]
) -> bool:

    for patt in patterns:

        if re.search(
            patt,
            value,
            flags=re.IGNORECASE
        ):
            return True

    return False

def matches_any_compiled_regex(
    value: str,
    patterns: list[re.Pattern]
) -> bool:

    for patt in patterns:

        if patt.search(value):

            return True

    return False

def url_passes_white_black_lists(
    runtime: RuntimeConfig,
    url: str
) -> bool:

    stats = GLOBAL_STATS

    whitelist = (
        runtime.cli_args.url_white_list
    )

    blacklist = (
        runtime.cli_args.url_black_list
    )

    if whitelist:

        if not matches_any_regex(
            url,
            whitelist
        ):

            stats.urls_rejected_whitelist += 1

            return False

    if blacklist:

        if matches_any_regex(
            url,
            blacklist
        ):

            stats.urls_rejected_blacklist += 1

            return False

    return True


# ---------------------------------------------------------------------------
# HTML URL EXTRACTION
# ---------------------------------------------------------------------------

TAG_ATTR_MAP = {

    "a":
        ["href"],

    "img":
        ["src"],

    "link":
        ["href"],

    "script":
        ["src"],

    "source":
        ["src", "srcset"]
}


def extract_urls_from_html(
    html: str,
    page_url: str,
    search_tags: list[str]
) -> list[str]:

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    discovered_urls: list[str] = []

    for tag_name in search_tags:

        attrs = TAG_ATTR_MAP.get(
            tag_name,
            []
        )

        for tag in soup.find_all(
            tag_name
        ):

            for attr_name in attrs:

                value = tag.get(
                    attr_name
                )

                if not value:
                    continue

                if attr_name == "srcset":

                    entries = value.split(",")

                    for entry in entries:

                        candidate = (
                            entry.strip()
                            .split(" ")[0]
                        )

                        if candidate:

                            normalized = normalize_url(page_url, candidate)

                            if is_supported_url(normalized):
                                discovered_urls.append(normalized)

                else:

                    normalized = normalize_url(page_url, value)

                    if is_supported_url(normalized):
                        discovered_urls.append(normalized)


    return discovered_urls


# ---------------------------------------------------------------------------
# FETCH PAGE
# ---------------------------------------------------------------------------

def fetch_page(
    runtime: RuntimeConfig,
    session: requests.Session,
    url: str
) -> str | None:

    try:

        response = session.get(
            url,
            timeout=runtime.cli_args.request_timeout
        )

        response.raise_for_status()

        content_type = (
            response.headers.get(
                "Content-Type",
                ""
            )
            .lower()
        )

        if "text/html" not in content_type:

            logging.debug(
                "Non HTML response: %s",
                url
            )

            return None

        return response.text

    except Exception as exc:

        logging.error(
            "Failed fetching URL: %s (%s)",
            url,
            exc
        )

        return None


# ---------------------------------------------------------------------------
# LEVEL LOOKUP
# ---------------------------------------------------------------------------

def get_level_config(
    runtime: RuntimeConfig,
    level: int
) -> CrawlLevelConfig | None:

    return (
        runtime
        .crawl_config
        .levels
        .get(level)
    )


# ---------------------------------------------------------------------------
# MATCH DISCOVERY
# ---------------------------------------------------------------------------

def find_matches_for_level(
    runtime: RuntimeConfig,
    level: int,
    urls: list[str]
) -> list[str]:

    level_cfg = get_level_config(
        runtime,
        level
    )

    if not level_cfg:
        return []

    matches: list[str] = []

    for url in urls:

        if matches_any_compiled_regex(
            url,
            level_cfg.compiled_regex
        ):

            matches.append(
                url
            )

    if (
        runtime
        .cli_args
        .sort_match_asc_by_filename
    ):

        matches.sort(
            key=lambda u:
            Path(
                urlparse(
                    u
                ).path
            ).name.lower()
        )

    return matches


# ---------------------------------------------------------------------------
# BFS RESULT
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class CrawlDiscoveryResult:

    matched_urls_by_level: dict[
        int,
        list[str]
    ] = field(
        default_factory=dict
    )


# ---------------------------------------------------------------------------
# BFS CRAWLER
# ---------------------------------------------------------------------------

def discover_matches(
    runtime: RuntimeConfig
) -> CrawlDiscoveryResult:

    session = create_http_session()

    visited: set[str] = set()
    
    queued: set[str] = set()

    result = CrawlDiscoveryResult()

    queue = deque()

    queue.append(
        (
            runtime.cli_args.base_url,
            0
        )
    )
    
    queued.add(
        runtime.cli_args.base_url
    )

    while queue:

        if (
            GLOBAL_STATS.urls_visited
            >=
            runtime.cli_args.max_urls_visited
        ):

            logging.warning(
                "Max URLs visited reached."
            )

            break

        current_url, depth = (
            queue.popleft()
        )

        if current_url in visited:

            GLOBAL_STATS.urls_skipped += 1

            continue

        visited.add(
            current_url
        )

        GLOBAL_STATS.urls_visited += 1

        logging.info(
            "Visiting [L%s] %s",
            depth,
            current_url
        )

        if not url_allowed_by_domain_rules(
            runtime,
            current_url
        ):
            continue

        if not url_passes_white_black_lists(
            runtime,
            current_url
        ):
            continue

        if not can_fetch_url(
            runtime,
            session,
            current_url
        ):
            continue

        html = fetch_page(
            runtime,
            session,
            current_url
        )

        if html is None:
            continue

        discovered_urls = (
            extract_urls_from_html(
                html,
                current_url,
                runtime.cli_args.search_in_tag_set
            )
        )

        matches = find_matches_for_level(
            runtime,
            depth,
            discovered_urls
        )

        if matches:

            result.matched_urls_by_level\
                .setdefault(
                    depth,
                    []
                )\
                .extend(matches)

            GLOBAL_STATS.matches_found += (
                len(matches)
            )

        level_cfg = get_level_config(
            runtime,
            depth
        )

        if (
            level_cfg
            and
            "RECURSE"
            in
            level_cfg.actions
            and
            depth
            <
            runtime.cli_args.max_rec_lvl
        ):

            for discovered_url in (
                discovered_urls
            ):

                #
                # Already queued?
                #

                if discovered_url in queued:

                    continue

                #
                # Already visited?
                #

                if discovered_url in visited:

                    continue

                #
                # Domain rules
                #

                if not url_allowed_by_domain_rules(
                    runtime,
                    discovered_url
                ):
                    continue

                #
                # White/black list
                #

                if not url_passes_white_black_lists(
                    runtime,
                    discovered_url
                ):
                    continue

                #
                # Robots
                #

                if not can_fetch_url(
                    runtime,
                    session,
                    discovered_url
                ):
                    continue

                queued.add(
                    discovered_url
                )

                queue.append(
                    (
                        discovered_url,
                        depth + 1
                    )
                )

    return result


# ---------------------------------------------------------------------------
# GLOBAL STATS INSTANCE
# ---------------------------------------------------------------------------

GLOBAL_STATS = CrawlStats()

# ---------------------------------------------------------------------------
# END OF CHUNK #2
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# FILE TYPE MATCHING
# ---------------------------------------------------------------------------

DOWNLOADED_URLS: set[str] = set()


def wildcard_to_regex(
    pattern: str
) -> str:

    escaped = re.escape(
        pattern
    )

    escaped = escaped.replace(
        r"\*",
        ".*"
    )

    return (
        "^"
        + escaped
        + "$"
    )


def extension_matches(
    extension: str,
    allowed_patterns: list[str]
) -> bool:

    if not allowed_patterns:
        return True

    extension = extension.lower()

    for patt in allowed_patterns:

        regex = wildcard_to_regex(
            patt.lower()
        )

        if re.match(
            regex,
            extension
        ):
            return True

    return False


def derive_extension_from_url(
    url: str
) -> str:

    parsed = urlparse(url)

    path = Path(
        parsed.path
    )

    return path.suffix.lower()


# ---------------------------------------------------------------------------
# CONTENT TYPE SUPPORT
# ---------------------------------------------------------------------------

CONTENT_TYPE_EXTENSION_MAP = {

    "image/jpeg":
        ".jpg",

    "image/jpg":
        ".jpg",

    "image/png":
        ".png",

    "image/gif":
        ".gif",

    "image/webp":
        ".webp",

    "application/pdf":
        ".pdf",

    "application/zip":
        ".zip"
}


def derive_extension_from_content_type(
    content_type: str
) -> str:

    content_type = (
        content_type
        .split(";")[0]
        .strip()
        .lower()
    )

    return (
        CONTENT_TYPE_EXTENSION_MAP
        .get(
            content_type,
            ""
        )
    )


# ---------------------------------------------------------------------------
# OUTPUT FILE NAMING
# ---------------------------------------------------------------------------

FILE_COUNTERS: dict[int, int] = {}


def get_next_file_number(
    level: int
) -> int:

    FILE_COUNTERS.setdefault(
        level,
        0
    )

    FILE_COUNTERS[level] += 1

    return FILE_COUNTERS[level]


def generate_output_filename(
    level: int,
    level_cfg: CrawlLevelConfig,
    extension: str
) -> str:

    file_number = (
        get_next_file_number(
            level
        )
    )

    ####parts = [
    ####    f"L{level}"
    ####]
    
    parts = []

    if level_cfg.output_prefix:

        parts.append(
            level_cfg.output_prefix
        )

    parts.append(
        ####f"{file_number:06d}"
        ####f"{file_number:03d}"
        f"{file_number:02d}"
        ####f"{file_number}"
    )

    if level_cfg.output_postfix:

        parts.append(
            level_cfg.output_postfix
        )

    filename = "_".join(
        parts
    )

    return (
        filename
        + extension
    )


# ---------------------------------------------------------------------------
# DOWNLOAD RESULTS
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DownloadResult:

    expected_files: list[str] = field(
        default_factory=list
    )

    successful_files: list[str] = field(
        default_factory=list
    )

    failed_files: list[str] = field(
        default_factory=list
    )


# ---------------------------------------------------------------------------
# FILE DOWNLOAD
# ---------------------------------------------------------------------------

def download_file(
    runtime: RuntimeConfig,
    session: requests.Session,
    url: str,
    output_file: Path
) -> bool:

    if runtime.cli_args.dry_run:

        logging.warning(
            "[DRY RUN] Would download: %s -> %s",
            url,
            output_file
        )

        return True

    try:

        with session.get(
            url,
            timeout=runtime.cli_args.request_timeout,
            stream=True
        ) as response:

            response.raise_for_status()

            with output_file.open(
                "wb"
            ) as fp:

                for chunk in (
                    response.iter_content(
                        chunk_size=8192
                    )
                ):

                    if chunk:

                        fp.write(
                            chunk
                        )

        return True

    except Exception as exc:

        logging.error(
            "Download failed: %s (%s)",
            url,
            exc
        )

        return False


# ---------------------------------------------------------------------------
# DOWNLOAD ELIGIBILITY
# ---------------------------------------------------------------------------

def determine_extension(
    session: requests.Session,
    runtime: RuntimeConfig,
    url: str
) -> str:

    #
    # Try URL extension first
    #

    ext = derive_extension_from_url(
        url
    )

    if ext:

        return ext

    #
    # HEAD request
    #

    try:

        response = session.head(
            url,
            allow_redirects=True,
            timeout=runtime.cli_args.request_timeout
        )

        content_type = (
            response.headers.get(
                "Content-Type",
                ""
            )
        )

        ext = derive_extension_from_content_type(
            content_type
        )

        if ext:

            return ext

    except Exception:

        pass

    #
    # GET fallback
    #

    try:

        response = session.get(
            url,
            allow_redirects=True,
            timeout=runtime.cli_args.request_timeout,
            stream=True
        )

        content_type = (
            response.headers.get(
                "Content-Type",
                ""
            )
        )

        ext = derive_extension_from_content_type(
            content_type
        )

        response.close()

        return ext

    except Exception:

        return ""


def is_download_candidate(
    level_cfg: CrawlLevelConfig,
    extension: str
) -> bool:

    return extension_matches(
        extension,
        level_cfg.file_types
    )


# ---------------------------------------------------------------------------
# DOWNLOAD ENGINE
# ---------------------------------------------------------------------------

def process_downloads(
    runtime: RuntimeConfig,
    discovery: CrawlDiscoveryResult
) -> DownloadResult:

    result = DownloadResult()

    session = create_http_session()

    for level, urls in (
        discovery
        .matched_urls_by_level
        .items()
    ):

        level_cfg = (
            get_level_config(
                runtime,
                level
            )
        )

        if not level_cfg:
            continue

        if (
            "DOWNLOAD"
            not in
            level_cfg.actions
        ):
            continue

        unique_urls = list(
            dict.fromkeys(
                urls
            )
        )

        for url in unique_urls:

            if url in DOWNLOADED_URLS:

                continue

            DOWNLOADED_URLS.add(
                url
            )

            extension = (
                determine_extension(
                    session,
                    runtime,
                    url
                )
            )

            if not extension:

                logging.debug(
                    "Unable to determine extension: %s",
                    url
                )

                continue

            if not is_download_candidate(
                level_cfg,
                extension
            ):

                continue

            output_name = (
                generate_output_filename(
                    level,
                    level_cfg,
                    extension
                )
            )

            output_path = (
                runtime
                .effective_output_dir
                / output_name
            )

            result.expected_files.append(
                str(output_path)
            )

            GLOBAL_STATS.files_expected += 1

            logging.info(
                "Downloading: %s",
                url
            )

            success = download_file(
                runtime,
                session,
                url,
                output_path
            )

            if success:

                GLOBAL_STATS.files_downloaded += 1

                result.successful_files.append(
                    str(output_path)
                )

            else:

                GLOBAL_STATS.files_failed += 1

                result.failed_files.append(
                    str(output_path)
                )
                
            if not runtime.cli_args.dry_run:
                logging.debug("Starting Sleep for 1 second")
                time.sleep(1)
                logging.debug("Finished Sleep for 1 second")

    return result


# ---------------------------------------------------------------------------
# SUMMARY REPORT
# ---------------------------------------------------------------------------

def print_summary(
    stats: CrawlStats,
    download_result: DownloadResult
) -> None:

    print()

    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)

    print(
        f"URLs Visited: "
        f"{stats.urls_visited}"
    )

    print(
        f"URLs Skipped: "
        f"{stats.urls_skipped}"
    )

    print(
        f"Whitelist Rejects: "
        f"{stats.urls_rejected_whitelist}"
    )

    print(
        f"Blacklist Rejects: "
        f"{stats.urls_rejected_blacklist}"
    )

    print(
        f"Matches Found: "
        f"{stats.matches_found}"
    )

    print(
        f"Files Expected: "
        f"{stats.files_expected}"
    )

    print(
        f"Files Downloaded: "
        f"{stats.files_downloaded}"
    )

    print(
        f"Files Failed: "
        f"{stats.files_failed}"
    )

    print(
        f"Elapsed Seconds: "
        f"{stats.elapsed_seconds:.2f}"
    )

    print("=" * 60)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main() -> int:

    start_time = time.time()

    try:

        cli_args = (
            parse_cli_args()
        )

        configure_logging(
            cli_args.debug,
            cli_args.log_file
        )

        runtime = (
            build_runtime_config(
                cli_args
            )
        )

        logging.info(
            "Starting crawl."
        )

        discovery = (
            discover_matches(
                runtime
            )
        )

        logging.info(
            "Starting downloads."
        )

        download_result = (
            process_downloads(
                runtime,
                discovery
            )
        )

        GLOBAL_STATS.elapsed_seconds = (
            time.time()
            - start_time
        )

        print_summary(
            GLOBAL_STATS,
            download_result
        )

        logging.info(
            "Completed successfully."
        )

        return 0

    except KeyboardInterrupt:

        logging.error(
            "Interrupted by user."
        )

        return 2

    except Exception as exc:

        logging.exception(
            "Fatal error: %s",
            exc
        )

        return 1


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    sys.exit(
        main()
    )

# ---------------------------------------------------------------------------
# END OF CHUNK #3
# ---------------------------------------------------------------------------



