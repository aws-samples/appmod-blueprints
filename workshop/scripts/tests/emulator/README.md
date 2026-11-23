# sweep-on-emulator

An integration test of the workshop teardown sweep (`workshop/scripts/sweep-workshop-resources.py`)
and of the issue #10 reconcile in `task enable-capability-logs`, run against
[AWS Emulator](https://github.com/aws/aws-emulator): a local, in-memory AWS endpoint with a fake
account `000000000000`. It complements the `MagicMock` unit tests (`test_sweep_*.py`,
`test_capability_logs_wait.py`) with real API behaviour: request validation, `DependencyViolation`
ordering, the exact `ConflictException` of issue #10, and prefix scoping across services.
The sweep takes about 30 s here and the whole run under 2 minutes once the downloads are
cached. A teardown on a real account takes 25 to 40 minutes.

CI: `.github/workflows/sweep-on-emulator.yml` runs on demand, and on pull requests and pushes to
`main` that touch any of these: the sweep, the root and workshop `Taskfile.yaml`, the cluster
provider Taskfiles (go-task parses them before it runs `enable-capability-logs`),
`gitops/addons/registry/`, `scripts/install-timing.sh`, the sweep and capability-logs tests, or
these scripts.

## What one run does (`run-all.sh`)

1. **Guard.** Fails if any `AWS_*` variable, or a GitHub OIDC token variable
   (`ACTIONS_ID_TOKEN_*`), is set (`guard_host_env` in `lib.sh`). The workflow has no secret, no
   OIDC role and `contents: read` only.
2. **Install** (`install.sh`). AWS Emulator **1.0.556**, pinned, from the official Debian package.
   The package's SHA-256 is checked, then its GPG signature against the AWS key fingerprint
   `98BC F336 A3BE 53B7 34E9 67C5 2E5B F49B D940 F624` published in the AWS Emulator docs.
   The package is extracted without root. go-task and yq are installed at pinned versions with
   pinned SHA-256s.
3. **Start.** `aws-emulator -b 127.0.0.1 -p 0 -t off`: loopback only (also checked with `ss`),
   a free port, no telemetry, and an isolated `HOME` for the emulator's generated keys and CA.
4. **Identity guard.** `sts get-caller-identity` must return `000000000000`. Every later command
   that calls AWS (the CLI, the sweep, go-task, `verify.py`) goes through `emu_run`. `emu_run`
   first checks that the endpoint is `https://127.0.0.1:<port>`, then starts the command from an
   empty environment that holds only the emulator's endpoint, keys and CA. `verify.py` checks the
   endpoint of each boto3 client again.
5. **Seed** (`seed.sh`). The leftovers of a failed teardown for `peeks`, and the same set for the
   control stack `peeks2`. The control prefix starts with `peeks` on purpose (#1111). The seed
   covers a spoke VPC (subnet, two SGs that reference each other, an ENI, an IGW, a route table, a
   `guardduty-data` endpoint), an EIP, a hub VPC, the hub and a spoke EKS cluster, the hub's kro
   capability, an IAM role, an S3 bucket with objects, ECR repositories, secrets, a log group, an
   SSM parameter and a DynamoDB table. Each resource goes in `manifest.tsv`.
6. **Issue #10** (`scenario-10.sh`). It injects a stale `peeks-hub-kro` delivery source on an old
   capability ARN, with a delivery that uses it. It checks that a plain `put-delivery-source` fails
   with AWS's exact `ConflictException`. It then runs the **real** `task enable-capability-logs`
   from the repository's `Taskfile.yaml` and checks that the task reconciles the source. A second
   run must change nothing.
7. **Sweep** (`run-sweep.sh`). The unmodified sweep runs with `us-west-2 peeks`.
8. **Verify** (`verify.py`). Every `peeks` resource in the manifest is gone, every `peeks2`
   resource is intact, and a name/tag scan finds no `peeks`, `peeks-*` or `peeks/*` resource left.
   It polls for up to 30 s, because some deletions finish asynchronously.

## Known emulator cases, and how the job treats them

| Case | Treatment |
|---|---|
| The §17 gate of the sweep counts a DynamoDB table in `DELETING` as present, so the sweep ends with `DESTROY INCOMPLETE`, RC=1, although the table is being deleted. It is a probable false residue, and whether AWS behaves the same is being checked separately. | The table **is** seeded, so the residue reaper is exercised. `run-sweep.sh` accepts RC=1 only if every resource that `DESTROY INCOMPLETE` lists is in `KNOWN_FALSE_RESIDUE`, and it emits a `::warning::`. `verify.py` then checks on its own that the table is gone. Any other residue, or any other exit code, fails the job. Once the sweep is fixed, RC becomes 0 and the list should be emptied. |
| CloudFront `ListVpcOrigins` is a stub in the emulator (`NotImplemented`). | The CloudFront reaper logs the error and the sweep carries on, which also exercises its error tolerance. No CloudFront resource is seeded. `run-sweep.sh` emits a `::notice::`. |
| The emulator keeps the same capability ARN when a capability is recreated. | The "previous incarnation" ARN of issue #10 is a synthetic one, injected directly. |
| The emulator, like AWS, refuses `aws:cloudformation:*` tags. | The CFN-owned IDE VPC path (`is_our_ide_vpc`) is not covered. It needs a real stack. |

## Not covered

The job does not run a real EKS (nodes, ENIs, capabilities that reconcile), `task install` or
`task destroy`, CloudFormation, the AMP, AMG, RDS and ELB reapers (nothing is seeded for them),
IAM policy evaluation, or the network timings of a real account. A test event is still needed
for those.

The job checks that resources end up deleted, not which reaper deleted them. A reaper whose
resource a later stage also removes can regress unnoticed: the §17 re-drive deletes the ECR repo
and releases a freed EIP, and the §14 orphan reaper deletes the spoke VPC (in this run the §10
spoke reaper always hits `DependencyViolation`, as designed, and §14 finishes the job).

## Running it locally

```bash
python3 -m venv /tmp/emu-venv
/tmp/emu-venv/bin/pip install --require-hashes -r workshop/scripts/tests/emulator/requirements.txt
/usr/bin/env -i HOME="$HOME" PATH="/tmp/emu-venv/bin:/usr/bin:/bin:/usr/sbin" \
  bash workshop/scripts/tests/emulator/run-all.sh
```

`env -i` starts from an empty environment, so the guard does not trip on your own AWS variables.
Everything goes under `EMU_WORK` (default `${TMPDIR:-/tmp}/sweep-emulator`), outside the checkout.
Linux x86_64 only. `EMU_DOWNLOAD_DIR` can point at a cache of the downloads, which are still
verified when cached.

## Bumping the emulator

The emulator ships several releases a day, and a release can change results. Change
`EMULATOR_VERSION` and `EMULATOR_DEB_SHA256` in `install.sh` together, run the job, and read the
differences. Versions are listed in
`https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS/versions.json`.
The AWS Emulator docs say that security fixes ship only in the latest release. A pinned version
stops getting them, so bump it regularly. The emulator only listens on loopback in this job.
