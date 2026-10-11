# Repository settings that I changed

From this point, every change reaches `main` through a pull request that has passed the same checks as a push. I changed the following settings on 6 October 2026 and I list them here so that they can be reviewed and reverted.

## Branch protection on `main`

| Setting | Value |
|---|---|
| Required status checks | Backend tests, Frontend build, PostgreSQL integration tests, Secret scan (gitleaks), Static analysis (Terraform and Helm), Build, scan and push images |
| Require a pull request before merging | yes, with 0 required approvals (a single developer cannot approve their own pull request) |
| Dismiss stale approvals | yes |
| Apply to administrators | yes, so that I follow the same flow as everyone else |
| Force pushes | blocked |
| Branch deletion | blocked |

The deploy job is not a required check, because it runs only on pushes to `main` and is skipped for pull requests.

## Proof that it works

I tried to push a commit straight to `main`. GitHub rejected it:

```text
remote: - Changes must be made through a pull request.
remote: - 5 of 5 required status checks are expected.
 ! [remote rejected] probe/direct-push-test -> main (protected branch hook declined)
```

`main` was unchanged afterwards (`2a94dbe`).

## How to revert

```bash
gh api -X DELETE repos/Ujjwaljain16/campusslot/branches/main/protection
```

## What the promotion workflow needs (v2)

The `Promote` workflow opens a pull request with the token of the workflow run. For that to work, **Settings, Actions, General, "Allow GitHub Actions to create and approve pull requests"** has to be on. It is off until it is switched on, and the workflow then fails with that message, which is the safe default.

A pull request that is opened with the default token does not start the other workflows (a rule of GitHub, to prevent loops). On a protected branch with required checks, such a pull request would wait for checks that never start. Closing the pull request and opening it again, as a person, starts them. In production the workflow would use the token of a GitHub App instead.

## Why

Direct pushes to `main` were the way that I built the project, and they are the reason for several of the red runs in [the DORA analysis](dora-analysis.md): the pipeline was a report that arrived after the change had already landed. With a protected branch, the pipeline is a gate that runs before the change lands.
