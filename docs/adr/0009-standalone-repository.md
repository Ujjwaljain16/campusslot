# ADR 0009: Build the capstone in its own repository

Status: accepted

## Context

The course repository holds one folder per lab, and the capstone needs its own pipeline, container registry packages and Helm chart.

## Options considered

- A folder `20-final-devops-project` inside the course repository.
- A separate public repository with a short pointer in the course repository.

## Decision

A standalone repository `campusslot`, and a pointer folder with a checklist in the course repository.

## Consequences

- GitHub Actions workflows must live at the root of the repository that they build, and the GHCR packages are named after it.
- The course repository stays a clean record of the labs, and the capstone can be reviewed on its own.
- A grader has to follow one link to find the project.

## What I would do in production

The same layout. A real product would also split the infrastructure code into its own repository with its own access rules.
