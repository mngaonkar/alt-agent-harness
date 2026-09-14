---
name: sysinfo
description: Report or diagnose this host's health - OS, Python version, CPU count, disk free space, process RSS, uptime, cwd and workspace path. Use when the user asks how the machine is doing, whether it is running out of memory or disk, or for any host status report.
version: 1.0.0
---

# Host diagnostics

## Getting the numbers

Call `host_status` for the full snapshot. Every field is a raw number, so
convert before presenting: bytes to KB/MB/GB, `uptime_s` to minutes or hours.

For a trend rather than a snapshot -- "is RSS climbing?" -- run
`scripts/rss_watch.py` with `run_script`, passing `{"samples": 5, "interval_s": 0.4}`.
It samples `ru_maxrss` repeatedly and reports the delta.

## Reading the results

`rss` is peak resident set size for this process, not system-wide memory.
`rss_unit` tells you the unit: `bytes` on macOS, `kb` on Linux. Convert before
comparing.

Disk numbers are for the volume that holds the workspace, not a RAM metric.
A few GB free is healthy; below ~500 MB is worth mentioning.

`uptime_s` is how long *this agent process* has been running, not system
uptime.

## Reporting

Lead with the answer to what was actually asked, then at most two or three
supporting numbers. Do not dump the whole JSON blob unless asked for everything.
