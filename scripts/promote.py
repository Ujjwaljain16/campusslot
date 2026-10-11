#!/usr/bin/env python3
"""Move a build from one environment to the next, and check that nothing skips a step.

    python3 scripts/promote.py status
    python3 scripts/promote.py promote --to dev --sha <commit>      # any build of this repository
    python3 scripts/promote.py promote --to staging                 # what dev runs now
    python3 scripts/promote.py promote --to prod                    # what staging runs now
    python3 scripts/promote.py check --base origin/v2               # the rules, for a pull request
    python3 scripts/promote.py appset --envs dev,staging            # the ApplicationSet, only for those environments

The state of an environment is two lines in gitops/envs/<env>/values.yaml: the tag of the backend image and the tag
of the frontend image. Both are the commit that CI built them from. Promoting means changing those two lines in the
next environment to the ones of the previous environment, so the change is a commit, a pull request, a review and a
diff of two lines, and the cluster follows because Argo CD follows Git.

The rules of "check" (they run in CI on every pull request):

  1. the tags are full commit hashes, never "latest" or a branch name
  2. in one environment the backend and the frontend tag are the same commit
  3. staging may only take the tags that dev has at the base of the pull request, and prod only the tags of staging,
     so a build cannot reach prod without having run in both environments before
  4. a change of the prod tags changes nothing else under gitops/envs, so that it is always one reviewable decision
  5. dev takes a commit that exists in this repository

Standard library only, so that it runs on a CI runner and on a laptop without an installation.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENVS = ["dev", "staging", "prod"]
UPSTREAM = {"staging": "dev", "prod": "staging"}  # where an environment gets its build from
SHA = re.compile(r"^[0-9a-f]{40}$")
APPSET = ROOT / "gitops" / "applicationset.yaml"


def values_path(env: str) -> Path:
    return ROOT / "gitops" / "envs" / env / "values.yaml"


def read_tags(text: str) -> dict[str, str]:
    """The image tags in the text of a values file: {"backend": sha, "frontend": sha}.

    The file has a fixed shape (backend: / image: / tag:), so the two lines are found by position and not with a
    YAML parser, which the standard library does not have."""
    tags: dict[str, str] = {}
    section = None
    in_image = False
    for line in text.splitlines():
        if re.match(r"^(backend|frontend):\s*$", line):
            section = line.split(":")[0]
            in_image = False
        elif re.match(r"^\S", line) and not line.startswith("#"):
            section = None
            in_image = False
        elif section and re.match(r"^  image:\s*$", line):
            in_image = True
        elif section and in_image:
            match = re.match(r'^    tag:\s*"?([^"\s#]+)"?', line)
            if match:
                tags[section] = match.group(1)
                in_image = False
        elif section and re.match(r"^  \S", line):
            in_image = False
    return tags


def write_tags(text: str, sha: str) -> str:
    """The same text with both tags replaced. Everything else, including the comments, stays as it is."""
    out = []
    section = None
    in_image = False
    for line in text.splitlines(keepends=True):
        if re.match(r"^(backend|frontend):\s*$", line):
            section = line.split(":")[0]
            in_image = False
        elif re.match(r"^\S", line) and not line.startswith("#"):
            section = None
            in_image = False
        elif section and re.match(r"^  image:\s*$", line):
            in_image = True
        elif section and in_image and re.match(r'^    tag:\s*"?[^"\s#]+"?', line):
            line = re.sub(r'(^    tag:\s*)"?[^"\s#]+"?', rf'\g<1>"{sha}"', line)
            in_image = False
        out.append(line)
    return "".join(out)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def tags_at(ref: str | None, env: str) -> dict[str, str] | None:
    """The tags of an environment in the working tree (ref is None) or at a git ref. None when the file is not there."""
    if ref is None:
        path = values_path(env)
        return read_tags(path.read_text(encoding="utf-8")) if path.exists() else None
    try:
        return read_tags(git("show", f"{ref}:gitops/envs/{env}/values.yaml"))
    except subprocess.CalledProcessError:
        return None


def status(_args) -> int:
    print(f"{'environment':<12} {'backend':<14} {'frontend':<14}")
    for env in ENVS:
        tags = tags_at(None, env) or {}
        print(f"{env:<12} {tags.get('backend', '-')[:12]:<14} {tags.get('frontend', '-')[:12]:<14}")
    return 0


def promote(args) -> int:
    target = args.to
    if target == "dev":
        if not args.sha:
            sys.exit("dev takes any build: give the commit with --sha")
        sha = args.sha
    else:
        upstream = tags_at(None, UPSTREAM[target])
        if not upstream or upstream.get("backend") != upstream.get("frontend"):
            sys.exit(f"{UPSTREAM[target]} has no single build to promote")
        sha = upstream["backend"]
        if args.sha and args.sha != sha:
            sys.exit(f"{target} takes what {UPSTREAM[target]} runs ({sha[:12]}), not {args.sha[:12]}")
    if not SHA.match(sha):
        sys.exit(f"not a full commit hash: {sha}")
    path = values_path(target)
    current = read_tags(path.read_text(encoding="utf-8"))
    if current.get("backend") == sha and current.get("frontend") == sha:
        print(f"{target} already runs {sha[:12]}: nothing to do")
        return 0
    path.write_text(write_tags(path.read_text(encoding="utf-8"), sha), encoding="utf-8", newline="\n")
    print(f"{target}: {current.get('backend', '-')[:12]} -> {sha[:12]}  ({path.relative_to(ROOT)})")
    return 0


def check(args) -> int:
    problems: list[str] = []
    changed: dict[str, dict[str, str]] = {}

    for env in ENVS:
        now = tags_at(None, env)
        if now is None:
            problems.append(f"{env}: gitops/envs/{env}/values.yaml is missing")
            continue
        for part in ("backend", "frontend"):
            tag = now.get(part)
            if tag is None:
                problems.append(f"{env}: no image tag for the {part}")
            elif not SHA.match(tag):
                problems.append(f"{env}: the {part} tag is not a full commit hash: {tag}")
        if now.get("backend") != now.get("frontend"):
            problems.append(f"{env}: the backend and the frontend run different commits")
        before = tags_at(args.base, env) if args.base else None
        if before is not None and before != now:
            changed[env] = now

    for env, now in changed.items():
        if env == "dev":
            try:
                git("cat-file", "-e", f"{now['backend']}^{{commit}}")
            except subprocess.CalledProcessError:
                problems.append(f"dev: the commit {now['backend'][:12]} does not exist in this repository")
            continue
        upstream_env = UPSTREAM[env]
        upstream = tags_at(args.base, upstream_env) or {}
        if now.get("backend") != upstream.get("backend"):
            problems.append(
                f"{env}: takes {now.get('backend', '-')[:12]}, but {upstream_env} runs "
                f"{upstream.get('backend', '-')[:12]} at the base. A build is promoted one step at a time."
            )

    if "prod" in changed and args.base:
        names = git("diff", "--name-only", args.base, "HEAD", "--", "gitops/envs").split()
        others = [n for n in names if n != "gitops/envs/prod/values.yaml"]
        if others:
            problems.append("prod: a change of the prod tags must change nothing else under gitops/envs: " + ", ".join(others))

    if changed:
        print("changed environments:", ", ".join(changed))
    if problems:
        print("PROMOTION RULES BROKEN:")
        for problem in problems:
            print("  -", problem)
        return 1
    print("the promotion rules hold" + (f" (compared with {args.base})" if args.base else " (no base given: only the shape was checked)"))
    return 0


def appset(args) -> int:
    """The ApplicationSet with only the environments that are wanted, for a cluster that cannot hold all of them."""
    wanted = [e.strip() for e in args.envs.split(",") if e.strip()]
    unknown = [e for e in wanted if e not in ENVS]
    if unknown:
        sys.exit(f"unknown environment: {', '.join(unknown)}")
    text = APPSET.read_text(encoding="utf-8")
    if args.revision:
        text = re.sub(r"(targetRevision:\s*)\S+", rf"\g<1>{args.revision}", text)
    lines = text.splitlines(keepends=True)
    out = []
    skip = False
    for line in lines:
        element = re.match(r"^\s+- env:\s*(\S+)", line)
        if element:
            skip = element.group(1) not in wanted
        elif skip and not re.match(r"^\s+autoSync:", line):
            skip = False
        if not skip:
            out.append(line)
    sys.stdout.write("".join(out))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("status").set_defaults(func=status)
    p = sub.add_parser("promote")
    p.add_argument("--to", required=True, choices=ENVS)
    p.add_argument("--sha")
    p.set_defaults(func=promote)
    c = sub.add_parser("check")
    c.add_argument("--base", help="the git ref that the change is compared with, for example origin/v2")
    c.set_defaults(func=check)
    a = sub.add_parser("appset")
    a.add_argument("--envs", default=",".join(ENVS))
    a.add_argument("--revision", help="the branch that Argo CD follows, instead of the one in the file")
    a.set_defaults(func=appset)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
