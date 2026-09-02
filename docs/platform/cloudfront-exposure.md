# Exposing the platform with CloudFront (no registered domain)

How to install the platform and reach it over HTTPS when you do not own a domain, using a
free `*.cloudfront.net` hostname. Written for a consumer driving the platform from its own
repository (the in-repo `workshop/` is the reference implementation of exactly this).

## The problem this solves

The platform needs its ingress hostname **before** it is installed. Keycloak realm URLs, the
OIDC issuer, every ingress host rule, and the ArgoCD and Backstage base URLs are all derived
from `domain`, and ArgoCD begins deploying addons at the end of the install. Installing with
an empty domain misconfigures all of them.

If you own a domain, this is trivial: set `domain` and install. If you do not, the obvious
approach is circular. A CloudFront hostname comes from a distribution, a distribution needs
an origin, the origin is the platform's load balancer, and the load balancer is created *by*
the install that needs the hostname.

The fix is to reserve the name before anything exists. `create-distribution` returns its
`DomainName` immediately, and CloudFront does not validate the origin at creation time, so a
distribution can be created with a deliberately unresolvable placeholder origin and hand back
a usable hostname in about a second. `domain` then becomes an ordinary static config value,
and the real origin is attached after the install.

## The three steps

```bash
# 1. Reserve the hostname. Seconds. No VPC, no load balancer, nothing else required.
domain=$(scripts/cloudfront-reserve-domain.sh)

# 2. Write it into config, then install. Nothing here is CloudFront-aware.
#    (your own config generator writes config.local.yaml)
task install

# 3. Point CloudFront at the load balancer the platform created.
scripts/cloudfront-attach-origin.sh
```

Both scripts are shipped by the platform and are the same ones the workshop uses. You should
not need to reimplement either.

### Required config

```yaml
domain: "d111111abcdef8.cloudfront.net"   # from step 1
insecure: true                            # REQUIRED — see below
hub:
  clusterName: "my-hub"                   # both scripts derive their names from this
aws:
  region: "us-west-2"
```

`insecure: true` is not optional in this mode. It does two things:

- the ALB serves plain HTTP, because CloudFront terminates TLS
- the platform creates the ALB as `internal` with the predictable name
  `<clusterName>-platform` (`gitops/addons/registry/core.yaml`), which is what step 3 looks
  for and what a CloudFront VPC origin requires

Everything else is a normal install. There is no CloudFront-specific platform configuration,
no domain resolution hook, and no ordering requirement beyond running step 3 after step 2.

## What each script does

**`scripts/cloudfront-reserve-domain.sh`** creates a distribution whose origin is
`placeholder.invalid` (reserved by RFC 2606, so it can never resolve) and prints the assigned
hostname. Idempotent: it finds an existing distribution by its `Comment`, which is
`<clusterName>-platform`, and returns that hostname instead of creating a second one. Safe in
a re-provisioning loop.

**`scripts/cloudfront-attach-origin.sh`** finds the ALB named `<clusterName>-platform`,
creates a CloudFront VPC origin bound to it, waits for that origin to deploy (measured at
about 9 minutes), and swaps the distribution's placeholder for it. Idempotent: it exits
having changed nothing if the distribution already points at the current ALB.

It also repairs drift. If the ALB is ever replaced, the VPC origin is left bound to a load
balancer that no longer exists and **every platform URL hangs with curl 000**. Because a VPC
origin cannot be re-pointed while attached to a distribution, the fix is create-new, swap,
delete-old, which the script performs automatically when it detects the mismatch. Re-running
it is the remedy for that failure mode.

Both read `hub.clusterName` and `aws.region` from `config.local.yaml` by default
(`PLATFORM_CONFIG_FILE` to relocate it), and both accept env overrides — `HUB_CLUSTER_NAME`,
`AWS_REGION`, `CF_COMMENT`, and for attach also `ALB_NAME` and `CF_TIMEOUT_SECONDS`.

Progress goes to stderr and the hostname to stdout, so `$(...)` captures the hostname
cleanly.

## Timeline and what is reachable when

| Step | Duration | State |
|---|---|---|
| reserve | ~1s | hostname exists, distribution serves errors |
| `task install` | ~30–40 min | platform comes up; ALB created near the end |
| attach | ~9 min | VPC origin deploys, then the swap |
| CloudFront propagation | a few min | URLs become reachable |

The distribution returning errors between steps 1 and 3 is expected. Nothing is pointed at it
yet and nothing depends on it being reachable during the install.

## What you own versus what the platform ships

You own your config generator, deciding when to run the three steps, and the AWS credentials.

The platform ships both CloudFront scripts, the ALB (created by the load balancer controller
during install), and all `insecure`-mode ingress behaviour.

**You do not need to create a VPC.** The platform creates its own, and the ALB lands in it.
Supplying `hub.network.vpcId` to install into an existing VPC is a separate, optional feature
that is only supported by the `kind-kro-ack` provider; `kind-crossplane` rejects it in
pre-flight (see [#833](https://github.com/aws-samples/appmod-blueprints/issues/833)). It is
not required for CloudFront exposure, and both providers work with this recipe.

## Security

Traffic from CloudFront to the platform stays on a private path. The ALB is `internal`, so it
has no public address, and CloudFront reaches it through a VPC origin from inside the VPC
rather than over the internet.

A tempting simplification is to skip the VPC origin and let CloudFront reach an
internet-facing ALB as an ordinary custom origin. That removes the 9-minute wait and the
attach step, but platform traffic then crosses the public internet in plaintext, since
`insecure: true` means the ALB speaks HTTP. Restricting the ALB's security group to the
CloudFront prefix list (`com.amazonaws.global.cloudfront.origin-facing`) controls *who* may
connect but does not encrypt anything. That trade is not recommended for anything beyond a
throwaway demo, which is why attach is a documented step rather than an optional one.

## Teardown

Neither script deletes anything. To remove the CloudFront resources, disable the distribution,
wait for `Deployed`, delete it, then delete the VPC origin. A distribution cannot be deleted
while enabled, and a VPC origin cannot be deleted while a distribution references it.

## Verification status

The mechanism was validated against live AWS before being built: a distribution created with
an unresolvable placeholder origin returned its hostname in 1 second, and
`update-distribution` accepted replacing a `CustomOriginConfig` with a `VpcOriginConfig` on a
live distribution, with the VPC origin reaching `Deployed` in 540 seconds.

Both scripts are covered by stubbed-CLI tests for their happy path, idempotent re-run, and
each failure guard. Neither has yet been exercised against a full end-to-end platform
install; the attach step in particular depends on an ALB that only exists after a real
install.
