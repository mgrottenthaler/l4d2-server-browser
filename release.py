#!/usr/bin/env python3
"""Cuts a release: bumps VERSION (the single source of truth also read by
steam_browser/version.py and served at GET /api/version), commits it, tags
it, and pushes - pushing the vX.Y tag is what triggers
.github/workflows/build-executables.yml's release job, which builds the
three platform executables and publishes them as GitHub Release assets.

Usage: python3 release.py major|minor [-y]
  major: 1.1 -> 2.0
  minor: 1.1 -> 1.2
  -y/--yes: push without the confirmation prompt
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
    major, minor = (int(x) for x in version.split("."))
    if part == "major":
        return "{}.0".format(major + 1)
    return "{}.{}".format(major, minor + 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("part", choices=["major", "minor"])
    parser.add_argument("-y", "--yes", action="store_true", help="push without confirming")
    args = parser.parse_args()

    if capture("git", "status", "--porcelain"):
        sys.exit("Working tree isn't clean - commit or stash first.")

    branch = capture("git", "rev-parse", "--abbrev-ref", "HEAD")
    if branch != "main":
        sys.exit("Not on main (currently on {}) - switch branches first.".format(branch))

    current = read_version()
    new = bump(current, args.part)
    tag = "v{}".format(new)

    if capture("git", "tag", "--list", tag):
        sys.exit("Tag {} already exists.".format(tag))

    with open(VERSION_FILE, "w") as f:
        f.write(new + "\n")

    run("git", "add", VERSION_FILE)
    run("git", "commit", "-m", "Bump version to {}".format(tag))
    run("git", "tag", tag)
    print("Tagged {} (was {}).".format(tag, current))

    if not args.yes:
        reply = input(
            "Push commit + tag {} to origin/main now? This triggers the "
            "release workflow and publishes a public GitHub Release. [y/N] ".format(tag)
        ).strip().lower()
        if reply != "y":
            print("Not pushed. Run `git push origin main {}` when ready.".format(tag))
            return

    run("git", "push", "origin", "main")
    run("git", "push", "origin", tag)
    print("Pushed {}. GitHub Actions will build and publish the release.".format(tag))


if __name__ == "__main__":
    main()
