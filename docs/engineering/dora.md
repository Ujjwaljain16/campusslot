# DORA metrics

Computed by `scripts/dora.py` from the Actions history of `Ujjwaljain16/campusslot` on 2026-10-06. Window: 2026-10-05 to 2026-10-05 (1 calendar days).

| Metric | Value | How it is measured |
|---|---|---|
| Deployment frequency | 22 green runs in 1 days, 22.0 per day | Green pipeline runs on main, ending with the kind deployment |
| Lead time for changes | median 4.6 min, longest 8.4 min | Commit time of the pushed head commit to the end of its green run |
| Change failure rate | 4 of 26 finished runs, 15 percent | Failed runs divided by finished runs, 4 cancelled runs left out |
| Time to restore | median 6.8 min, longest 26.1 min | End of a failed run to the end of the next green run |

## Green runs per day

| Day | Green runs |
|---|---|
| 2026-10-05 | 22 |

## Failed runs

| Run | Commit | Restored after |
|---|---|---|
| 37303336401 | `c84e634` Add troubleshooting labs with real transcripts, final HPA timeline and | 7.8 min |
| 37306992298 | `80739c6` Add Terraform for a VPC and EKS cluster with a reviewed, non-empty pla | 26.1 min |
| 37309510333 | `f53e1d8` Fix node group subnets to assign public IPs, add apply and verificatio | 3.7 min |
| 37317474907 | `dc987ac` Reword the page subtitle to state the booking guarantee plainly | 5.7 min |
