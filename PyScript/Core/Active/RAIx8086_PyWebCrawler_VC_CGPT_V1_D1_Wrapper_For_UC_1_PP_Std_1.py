#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Optional


# ------------------------------------------------------------------
# HARD-CODED SETTINGS
# ------------------------------------------------------------------

CRAWLER_SCRIPT = (
    "RAIx8086_PyWebCrawler_VC_CGPT_V1_D1"
)

OUTPUT_BASE_DIR = (
    ## TODO for User: Put here some File System Path on Your System
    r"<TODO_FOR_USER_INITIALIZE_WITH_SOME_FILE_SYSTEM_PATH_ON_YOUR_SYSTEM>"
)

MAX_REC_LVL = "0"

SEARCH_TAG_SET = "a"


# ------------------------------------------------------------------
# ARG PARSER
# ------------------------------------------------------------------

def parse_bool(value: str) -> bool:

    value = value.strip().lower()

    if value in (
        "true",
        "1",
        "yes",
        "y"
    ):
        return True

    if value in (
        "false",
        "0",
        "no",
        "n"
    ):
        return False

    raise argparse.ArgumentTypeError(
        f"Invalid boolean value: {value}"
    )


def build_arg_parser():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--baseUrl",
        required=True
    )

    parser.add_argument(
        "--regExPatt",
        required=True
    )

    parser.add_argument(
        "--outFilePrefix",
        required=True
    )

    parser.add_argument(
        "--numSavedFiles",
        type=int,
        default=-(2**63)
    )

    parser.add_argument(
        "--skipUserConfirmation",
        type=parse_bool,
        default=False
    )

    return parser


# ------------------------------------------------------------------
# BUILD CRAWL CONFIG JSON
# ------------------------------------------------------------------

def build_crawl_config_json(
    regex_pattern: str,
    output_prefix: str
) -> str:

    config = {
        "levels": {
            "0": {
                "regex": [
                    regex_pattern
                ],
                "actions": [
                    "DOWNLOAD"
                ],
                "outputPrefix": output_prefix
            }
        }
    }

    return json.dumps(
        config,
        separators=(",", ":")
    )


# ------------------------------------------------------------------
# BUILD COMMAND
# ------------------------------------------------------------------

def build_command(
    args,
    dry_run: bool
):

    crawl_config_json = (
        build_crawl_config_json(
            args.regExPatt,
            args.outFilePrefix
        )
    )

    cmd = [
        sys.executable,
        CRAWLER_SCRIPT,

        "--baseUrl",
        args.baseUrl,

        "--maxRecLvl",
        MAX_REC_LVL,

        "--outputBaseDir",
        OUTPUT_BASE_DIR,

        "--searchInTagSet",
        SEARCH_TAG_SET,

        "--crawlConfig",
        crawl_config_json,

        "--debug"
    ]

    if dry_run:
        cmd.append("--dryRun")

    return cmd


# ------------------------------------------------------------------
# EXECUTE COMMAND
# ------------------------------------------------------------------

def execute_command(cmd):

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True
    )

    return result


# ------------------------------------------------------------------
# SUMMARY VALUE EXTRACTION
# ------------------------------------------------------------------

def extract_summary_value(
    text: str,
    key: str
) -> Optional[int]:

    pattern = (
        rf"{re.escape(key)}\s*(\d+)"
    )

    match = re.search(
        pattern,
        text,
        flags=re.IGNORECASE
    )

    if not match:
        return None

    return int(
        match.group(1)
    )


# ------------------------------------------------------------------
# VALIDATION
# ------------------------------------------------------------------

def validate_dry_run(
    proc,
    num_saved_files: int
):

    warnings = []
    errors = []

    stdout_text = proc.stdout or ""
    stderr_text = proc.stderr or ""

    #
    # Print logs first
    #

    print()
    print("=" * 80)
    print("STDOUT")
    print("=" * 80)
    print(stdout_text)

    print()
    print("=" * 80)
    print("STDERR")
    print("=" * 80)
    print(stderr_text)

    #
    # Exit code
    #

    if proc.returncode != 0:

        errors.append(
            f"Process returned non-zero exit code: "
            f"{proc.returncode}"
        )

    #
    # stderr
    #

    if stderr_text.strip():

        errors.append(
            "stderr contains data."
        )

    #
    # ERROR lines
    #

    if re.search(
        r"\bERROR\b",
        stdout_text,
        flags=re.IGNORECASE
    ):
        errors.append(
            "ERROR log lines detected."
        )

    #
    # WARN lines
    #

    if re.search(
        r"\bWARN(?:ING)?\b",
        stdout_text,
        flags=re.IGNORECASE
    ):
        warnings.append(
            "WARNING log lines detected."
        )

    matches_found = extract_summary_value(
        stdout_text,
        "Matches Found:"
    )

    files_expected = extract_summary_value(
        stdout_text,
        "Files Expected:"
    )

    files_downloaded = extract_summary_value(
        stdout_text,
        "Files Downloaded:"
    )

    files_failed = extract_summary_value(
        stdout_text,
        "Files Failed:"
    )

    #
    # Files Failed
    #

    if files_failed is None:

        errors.append(
            "Unable to locate 'Files Failed:'"
        )

    elif files_failed != 0:

        errors.append(
            f"Files Failed = {files_failed}"
        )

    #
    # Matches vs Expected
    #

    if (
        matches_found is not None
        and
        files_expected is not None
    ):

        if matches_found != files_expected:

            warnings.append(
                f"Matches Found ({matches_found}) "
                f"!= Files Expected ({files_expected})"
            )

    #
    # Expected vs Downloaded
    #

    if (
        files_expected is not None
        and
        files_downloaded is not None
    ):

        if files_expected != files_downloaded:

            errors.append(
                f"Files Expected ({files_expected}) "
                f"!= Files Downloaded ({files_downloaded})"
            )

    #
    # numSavedFiles validation
    #

    if num_saved_files >= 0:

        if (
            matches_found is not None
            and
            matches_found != num_saved_files
        ):

            warnings.append(
                f"Matches Found ({matches_found}) "
                f"!= numSavedFiles ({num_saved_files})"
            )

        if (
            files_downloaded is not None
            and
            files_downloaded != num_saved_files
        ):

            errors.append(
                f"Files Downloaded ({files_downloaded}) "
                f"!= numSavedFiles ({num_saved_files})"
            )

    passed = (
        len(errors) == 0
    )

    return (
        passed,
        warnings,
        errors
    )


# ------------------------------------------------------------------
# PRINT VALIDATION REPORT
# ------------------------------------------------------------------

def print_validation_report(
    passed,
    warnings,
    errors
):

    print()
    print("=" * 80)
    print("VALIDATION REPORT")
    print("=" * 80)

    if warnings:

        print()
        print("WARNINGS:")

        for item in warnings:

            print(
                f"  [WARN] {item}"
            )

    if errors:

        print()
        print("ERRORS:")

        for item in errors:

            print(
                f"  [ERROR] {item}"
            )

    print()

    if passed:

        print(
            "OVERALL RESULT : PASS"
        )

    else:

        print(
            "OVERALL RESULT : FAIL"
        )

    print("=" * 80)


# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------

def main():

    parser = build_arg_parser()

    args = parser.parse_args()

    #
    # Dry run
    #

    dry_cmd = build_command(
        args,
        dry_run=True
    )

    print()
    print("Running DRY RUN...")
    print()

    proc = execute_command(
        dry_cmd
    )

    (
        validation_passed,
        warnings,
        errors
    ) = validate_dry_run(
        proc,
        args.numSavedFiles
    )

    print_validation_report(
        validation_passed,
        warnings,
        errors
    )

    if not validation_passed:

        print()
        print(
            "Validation FAILED."
        )

        return 1

    #
    # Confirmation
    #

    run_real_command = False

    if args.skipUserConfirmation:

        run_real_command = True

    else:

        answer = input(
            "\nProceed with actual download? (Y/N): "
        ).strip()

        if answer.lower() == "y":

            run_real_command = True

        else:

            print(
                "\nUser chose not to proceed."
            )

            return 0

    #
    # Real run
    #

    if run_real_command:

        print()
        print(
            "Running ACTUAL DOWNLOAD..."
        )
        print()

        real_cmd = build_command(
            args,
            dry_run=False
        )

        result = execute_command(
            real_cmd
        )

        print(result.stdout)

        if result.stderr:

            print(result.stderr)

        return result.returncode

    return 0


if __name__ == "__main__":

    sys.exit(
        main()
    )
