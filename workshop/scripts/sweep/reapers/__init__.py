"""Per-service teardown reapers (issue #924, principle #2).

Each reaper takes the shared SweepContext and performs one section of the sweep.
The orchestrator calls them in the exact original order — the order is
load-bearing (e.g. load balancers before EIPs before the VPC reaper).
"""
