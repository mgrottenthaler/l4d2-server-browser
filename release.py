#!/usr/bin/env python3
"""Cuts a release: bumps VERSION (the single source of truth also read by
steam_browser/version.py and served at GET /api/version), commits it, tags
it, and pushes - pushing the vX.Y tag is what triggers
.github/workflows/build-executables.yml's release job, which builds the
three platform executables and publishes them as GitHub Release assets.

The confirmation prompt runs *before* anything is committed or tagged, and
commit+tag+push happen back to back right after - declining or Ctrl-C'ing
the prompt leaves the tree exactly as it started, never with a dangling
local-only bump commit/tag to clean up later.

Usage: python3 release.py major|minor [-y]
  major: 1.1 -> 2.0
  minor: 1.1 -> 1.2
  -y/--yes: skip the confirmation prompt
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(HERE, "VERSION")


def run(*args):
    subprocess.run(args, cwd=HERE, check=True)


def capture(*args):
    return subprocess.run(args, cwd=HERE, check=True, capture_output=True, text=True).stdout.strip()


def read_version():
    with open(VERSION_FILE, "r") as f:
        return f.read().strip()


def bump(version, part):
    try:
        major, minor = (int(x) for x in version.split("."))
    except ValueError:
        sys.exit("VERSION file is malformed (expected MAJOR.MINOR, got {!r}).".format(version))
    if part == "major":
        return "{}.0".format(major + 1)
    return "{}.{}".format(major, minor + 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("part", choices=["major", "minor"])
    parser.add_argument("-y", "--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args()

    if capture("git", "status", "--porcelain"):
        sys.exit("Working tree isn't clean - commit or stash first.")

    branch = capture("git", "rev-parse", "--abbrev-ref", "HEAD")
    if branch != "main":
        sys.exit("Not on main (currently on {}) - switch branches first.".format(branch))

    run("git", "fetch", "origin", "main")
    ahead_behind = capture(
        "git", "rev-list", "--left-right", "--count", "main...origin/main"
    )
    ahead, behind = (int(x) for x in ahead_behind.split())
    if ahead:
        sys.exit(
            "main is {} commit(s) ahead of origin/main - push or reset before "
            "releasing (a previous release run may have been interrupted "
            "before pushing).".format(ahead)
        )
    if behind:
        sys.exit("main is behind origin/main - pull first.")

    current = read_version()
    new = bump(current, args.part)
    tag = "v{}".format(new)

    # Checked against the remote directly rather than local tags: the
    # earlier `git fetch origin main` only updates the main ref, not tags,
    # so a tag created out-of-band (another clone, a previous interrupted
    # run) could exist on origin without being visible locally - and
    # discovering that only when `git push origin tag` fails, after `git
    # push origin main` already succeeded, would leave main pushed with no
    # matching tag.
    if capture("git", "ls-remote", "--tags", "origin", "refs/tags/{}".format(tag)):
        sys.exit("Tag {} already exists on origin.".format(tag))

    if not args.yes:
        try:
            reply = input(
                "Bump {} -> {}, commit, tag, and push to origin/main now? "
                "This triggers the release workflow and publishes a public "
                "GitHub Release. [y/N] ".format(current, new)
            ).strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted - nothing was changed.")
            return
        if reply != "y":
            print("Aborted - nothing was changed.")
            return

    with open(VERSION_FILE, "w") as f:
        f.write(new + "\n")

    run("git", "add", VERSION_FILE)
    run("git", "commit", "-m", "Bump version to {}".format(tag))
    run("git", "tag", tag)
    run("git", "push", "origin", "main")
    run("git", "push", "origin", tag)
    print("Pushed {}. GitHub Actions will build and publish the release.".format(tag))


if __name__ == "__main__":
    main()
