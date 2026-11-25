"""Every external chart pinned in gitops/addons/registry must be seen by Renovate, once.

The ``defaultVersion`` custom managers in renovate.json were written when the pins lived
in a file literally named ``addons.yaml``, so their file pattern is ``/addons\\.ya?ml$/``.
The pins have since moved to ``gitops/addons/registry/*.yaml``, which that pattern does
not match, and the only remaining ``addons.yaml`` (gitops/bootstrap) is an ApplicationSet
with no pins. The result was silent: Renovate kept running weekly and reported nothing,
while every addon chart aged in place and had to be bumped by hand (#1310). A pin that no
manager matches never gets a CVE bump, so the gap is tested rather than trusted.

Matching too much is as bad as matching too little. The managers walk from ``chartName``
to ``defaultVersion`` through a bounded line window, and a window that can step over a
column-0 line pairs one addon's chart with the next addon's repository and version --
which both loses the real pins and invents a bump for a chart that never had that
version. So the windows only accept indented or blank lines, and the tests below assert
the exact set of extracted dependencies, not merely that each pin appears somewhere.

The tests drive the real matchStrings from renovate.json against the real registry files.
Renovate's regexes are JavaScript. Named groups are spelled ``(?<n>`` there and ``(?P<n>``
in Python, so they are rewritten; the bounded lazy repetition and character classes used
here behave the same in both engines. The one known divergence, ``\\s`` over exotic
control characters such as U+0085 and U+FEFF, cannot be reached by these patterns unless a
registry file grows one, which no current file does.

Entries that carry ``path`` instead of ``chartName`` are charts vendored in this repo
(addons/charts/*). They have no upstream to poll and must stay unmatched.
"""

import glob
import json
import os
import re

import yaml

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGISTRY = os.path.join(REPO, "gitops", "addons", "registry")
CONFIG = os.path.join(REPO, "renovate.json")


def _managers():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)["customManagers"]


def _covers(patterns, rel):
    """Renovate managerFilePatterns: /regex/ or a plain suffix."""
    for pattern in patterns:
        if pattern.startswith("/") and pattern.endswith("/"):
            if re.search(pattern[1:-1], rel):
                return True
        elif rel.endswith(pattern):
            return True
    return False


def _render(template, groups):
    for name, value in groups.items():
        if value is not None:
            template = template.replace("{{{%s}}}" % name, value)
    return template


def _deps_in_text(text, rel):
    """Every dependency Renovate's custom managers extract from one file's text."""
    deps = []
    for manager in _managers():
        if not _covers(manager["managerFilePatterns"], rel):
            continue
        for match_string in manager["matchStrings"]:
            python_re = re.sub(r"\(\?<(?![=!])", "(?P<", match_string)
            for match in re.finditer(python_re, text):
                groups = match.groupdict()
                name = groups.get("depName")
                if name is None and "depNameTemplate" in manager:
                    name = _render(manager["depNameTemplate"], groups)
                url = groups.get("registryUrl")
                if url is None and "registryUrlTemplate" in manager:
                    url = _render(manager["registryUrlTemplate"], groups)
                deps.append((name, url, groups.get("currentValue"), manager.get("datasourceTemplate")))
    return deps


def _registry_files():
    paths = glob.glob(os.path.join(REGISTRY, "*.yaml")) + glob.glob(
        os.path.join(REGISTRY, "*.yml")
    )
    return sorted(paths)


def _deps_in_file(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return _deps_in_text(f.read(), rel)


def _entries():
    """(file, addon, entry) for every registry entry that pins a defaultVersion."""
    for path in _registry_files():
        rel = os.path.relpath(path, REPO)
        with open(path, encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
        for addon, entry in doc.items():
            if isinstance(entry, dict) and "defaultVersion" in entry:
                yield rel, addon, entry


def _external():
    return [(r, a, e) for r, a, e in _entries() if "chartName" in e]


def _vendored():
    return [(r, a, e) for r, a, e in _entries() if "chartName" not in e]


def _expected_dep(entry):
    """The coordinate Renovate must produce for one registry entry."""
    repository = str(entry["chartRepository"])
    version = str(entry["defaultVersion"])
    chart = entry["chartName"]
    if repository.startswith("https://"):
        return (chart, repository, version, "helm")
    host = repository.split("/")[0]
    path = entry.get("chartNamespace") or "/".join(repository.split("/")[1:])
    return (f"{path}/{chart}", f"https://{host}", version, "docker")


def test_registry_has_pins_to_track():
    """Guard the guard: if the registry moved again, the rest proves nothing."""
    assert _external(), f"no chartName pin found under {REGISTRY}"


def test_every_external_chart_pin_is_tracked():
    untracked = []
    for rel, addon, entry in _external():
        if _expected_dep(entry) not in _deps_in_file(rel):
            untracked.append(f"{rel}:{addon} -> {_expected_dep(entry)}")
    assert not untracked, "chart pins no renovate manager matches: " + ", ".join(untracked)


def test_no_extra_dependencies():
    """The extracted set must be exactly the pins, with no duplicate or invented dep.

    An ``any hit`` assertion passes just as happily with a second, broken manager
    alongside the right one, or with a window that swallowed a neighbouring addon.
    Every registry file is checked, including the ones that pin nothing, so a file
    producing only spurious matches is caught too.
    """
    for path in _registry_files():
        rel = os.path.relpath(path, REPO)
        expected = sorted(_expected_dep(e) for r, _, e in _external() if r == rel)
        got = sorted(_deps_in_file(rel))
        assert got == expected, (
            f"{rel}: renovate extracts {len(got)} dep(s), the file pins {len(expected)}\n"
            f"  unexpected: {sorted(set(got) - set(expected))}\n"
            f"  missing:    {sorted(set(expected) - set(got))}"
        )


def test_oci_charts_get_their_repository_path():
    """An OCI pin needs host and path split, or the tag lookup 404s.

    ``chartRepository: public.ecr.aws`` plus ``chartNamespace: aws-controllers-k8s``
    addresses public.ecr.aws/aws-controllers-k8s/<chart>; a manager that drops the
    namespace would poll public.ecr.aws/<chart>, which does not exist.
    """
    checked = 0
    for rel, addon, entry in _external():
        if str(entry["chartRepository"]).startswith("https://"):
            continue
        name, url, version, datasource = _expected_dep(entry)
        assert (name, url, version, datasource) in _deps_in_file(rel), (
            f"{rel}:{addon} OCI pin not addressed as {datasource} {url}/{name}"
        )
        checked += 1
    assert checked, "no OCI pin exercised"


def test_https_charts_use_the_helm_datasource():
    checked = 0
    for rel, addon, entry in _external():
        if not str(entry["chartRepository"]).startswith("https://"):
            continue
        assert _expected_dep(entry) in _deps_in_file(rel), f"{rel}:{addon} https pin not matched"
        checked += 1
    assert checked, "no https pin exercised"


def test_vendored_charts_are_not_polled_upstream():
    """A chart built from addons/charts/* has no upstream version to look up."""
    for rel, addon, entry in _vendored():
        version = str(entry["defaultVersion"])
        assert "path" in entry, f"{rel}:{addon} has neither chartName nor path"
        for name, url, current, _ in _deps_in_file(rel):
            assert current != version or name is None, (
                f"{rel}:{addon} is vendored in this repo but renovate would poll {url}/{name}"
            )


SPILL_SHAPES = {
    "https": (
        # OCI entry the https manager does not match, then a short https entry, then an
        # entry with no defaultVersion, then another https entry.
        "ack-s3:\n"
        "  namespace: ack-system\n"
        "  chartName: s3-chart\n"
        "  chartNamespace: aws-controllers-k8s\n"
        "  chartRepository: public.ecr.aws\n"
        "  defaultVersion: '1.3.1'\n"
        "\n"
        "short-https-addon:\n"
        "  namespace: foo\n"
        "  chartName: foo\n"
        "  chartRepository: https://charts.example.org\n"
        "  defaultVersion: '9.9.9'\n"
        "\n"
        "no-version-https:\n"
        "  namespace: bar\n"
        "  chartName: bar\n"
        "  chartRepository: https://charts.example.org/bar\n"
        "  releaseName: bar\n"
        "\n"
        "last-https:\n"
        "  namespace: baz\n"
        "  chartName: baz\n"
        "  chartRepository: https://charts.example.org/baz\n"
        "  defaultVersion: '4.4.4'\n",
        [
            ("aws-controllers-k8s/s3-chart", "https://public.ecr.aws", "1.3.1", "docker"),
            ("foo", "https://charts.example.org", "9.9.9", "helm"),
            ("baz", "https://charts.example.org/baz", "4.4.4", "helm"),
        ],
    ),
    "chartNamespace": (
        # An ACK-shaped entry with no defaultVersion, followed by a complete one.
        "ack-nover:\n"
        "  namespace: ack-system\n"
        "  chartName: nover-chart\n"
        "  chartNamespace: aws-controllers-k8s\n"
        "  chartRepository: public.ecr.aws\n"
        "  releaseName: nover\n"
        "\n"
        "ack-ok:\n"
        "  namespace: ack-system\n"
        "  chartName: ok-chart\n"
        "  chartNamespace: aws-controllers-k8s\n"
        "  chartRepository: public.ecr.aws\n"
        "  defaultVersion: '7.7.7'\n",
        [("aws-controllers-k8s/ok-chart", "https://public.ecr.aws", "7.7.7", "docker")],
    ),
    "ghcr": (
        # A ghcr entry with no defaultVersion, followed by a complete one.
        "ghcr-nover:\n"
        "  namespace: g1\n"
        "  chartName: ga\n"
        "  chartRepository: ghcr.io/org/repo\n"
        "  releaseName: ga\n"
        "\n"
        "ghcr-ok:\n"
        "  namespace: g2\n"
        "  chartName: gb\n"
        "  chartRepository: ghcr.io/org/repo2\n"
        "  defaultVersion: '4.5.6'\n",
        [("org/repo2/gb", "https://ghcr.io", "4.5.6", "docker")],
    ),
    "comment": (
        # A column-0 comment inside an addon block, which these files use heavily
        # between entries, must not drop the pin that follows it.
        "commented:\n"
        "  namespace: c1\n"
        "  chartName: cc\n"
        "# a column-0 note, as the registry files write them\n"
        "  chartRepository: https://charts.example.org/cc\n"
        "  defaultVersion: '3.2.1'\n",
        [("cc", "https://charts.example.org/cc", "3.2.1", "helm")],
    ),
    "comment-chartNamespace": (
        "ack-commented:\n"
        "  namespace: ack-system\n"
        "  chartName: cm-chart\n"
        "# why this controller is pinned here\n"
        "  chartNamespace: aws-controllers-k8s\n"
        "  chartRepository: public.ecr.aws\n"
        "# and why this version\n"
        "  defaultVersion: '2.2.2'\n",
        [("aws-controllers-k8s/cm-chart", "https://public.ecr.aws", "2.2.2", "docker")],
    ),
    "comment-ghcr": (
        "ghcr-commented:\n"
        "  namespace: g3\n"
        "  chartName: gc\n"
        "# a column-0 note\n"
        "  chartRepository: ghcr.io/org/repo3\n"
        "  defaultVersion: '1.1.1'\n",
        [("org/repo3/gc", "https://ghcr.io", "1.1.1", "docker")],
    ),
    "version-before-repository": (
        # The https manager's second matchString: defaultVersion above chartRepository.
        # No registry entry is written this way today, but the pattern exists, so it
        # gets its own shape rather than relying on the first string's coverage.
        "reversed-order:\n"
        "  namespace: r1\n"
        "  chartName: rr\n"
        "  defaultVersion: '2.0.1'\n"
        "# a column-0 note between the two fields\n"
        "  chartRepository: https://charts.example.org/rr\n",
        [("rr", "https://charts.example.org/rr", "2.0.1", "helm")],
    ),
}


def _reversed_entry(name, ver, gap, eol="\n", blank_in_gap=False):
    """A reversed-order entry, to exercise the second matchString's own windows."""
    filler = "".join(f"  filler{i}: value{i}{eol}" for i in range(gap))
    if blank_in_gap:
        filler += eol
    return (
        f"{name}-entry:{eol}"
        f"  chartName: {name}{eol}"
        + filler
        + f"  defaultVersion: '{ver}'{eol}"
        + filler
        + f"  chartRepository: https://charts.example.org/{name}{eol}"
    )

# Each manager has its own windows, so the window properties that are not about
# spilling -- tolerating a CRLF blank line, and the line bound -- are generated for
# every addressing shape instead of being written out once for the https one.


# Stated here on purpose, NOT read from renovate.json. Deriving it would make the
# fixtures below regenerate with any change to the config, so narrowing the window
# would pass its own test -- a fixture that cannot fail. test_window_bound_is_the_one
# the_fixtures_assume keeps the two in step instead.
WINDOW_BOUND = 20


REGISTRY_FILE_PATTERN = "/gitops/addons/registry/.+\\.ya?ml$/"


def _registry_window_bounds():
    """The bounds of every window on a manager declared for the registry.

    Selected by the registry file pattern being listed on the manager, not by what its
    matchStrings look like: a mutation to a window must not be able to drop the manager
    out of this test's scope. The older ArgoCD-Application managers match the registry
    path too, through the broader `/gitops/.+\\.ya?ml$/`, but they are not declared for
    it and carry their own unrelated bounds.
    """
    bounds = set()
    for manager in _managers():
        if REGISTRY_FILE_PATTERN not in manager["managerFilePatterns"]:
            continue
        for match_string in manager.get("matchStrings") or []:
            bounds.update(re.findall(r"\)\{0,(\d+)\}\?|\)(\*)\?", match_string))
    return {a or b for a, b in bounds}

FLAVOURS = {
    "https": (
        ["chartRepository: https://charts.example.org/{name}", "defaultVersion: '{ver}'"],
        lambda name, ver: (name, f"https://charts.example.org/{name}", ver, "helm"),
    ),
    "chartNamespace": (
        [
            "chartNamespace: aws-controllers-k8s",
            "chartRepository: public.ecr.aws",
            "defaultVersion: '{ver}'",
        ],
        lambda name, ver: (f"aws-controllers-k8s/{name}", "https://public.ecr.aws", ver, "docker"),
    ),
    "ghcr": (
        ["chartRepository: ghcr.io/org/{name}", "defaultVersion: '{ver}'"],
        lambda name, ver: (f"org/{name}/{name}", "https://ghcr.io", ver, "docker"),
    ),
}


def _entry(flavour, name, ver, gap=0, eol="\n", blank_in_gap=False, gaps=None):
    """One registry entry whose fields are `gap` lines apart, with the given line end.

    `blank_in_gap` puts an empty line in each gap, which is what makes the window's
    blank-line branch matter: with CRLF line ends that branch has to accept \\r\\n.
    `gaps` restricts the padding to those gap indexes, so one window can be targeted
    on its own.
    """
    fields, _ = FLAVOURS[flavour]
    filler = "".join(f"  filler{i}: value{i}{eol}" for i in range(gap))
    if blank_in_gap:
        filler += eol
    body = f"{name}-entry:{eol}  chartName: {name}{eol}"
    for index, field in enumerate(fields):
        body += (filler if gaps is None or index in gaps else "")
        body += "  " + field.format(name=name, ver=ver) + eol
    return body


for _flavour, (_fields, _dep) in FLAVOURS.items():
    # a CRLF file with a blank line inside each gap of the entry: the blank branch has
    # to accept \r\n, or the pin is lost on a checkout that carries CRLF
    SPILL_SHAPES[f"crlf-{_flavour}"] = (
        _entry(_flavour, f"cr{_flavour[:2]}", "4.0.0", gap=1, eol="\r\n", blank_in_gap=True),
        [_dep(f"cr{_flavour[:2]}", "4.0.0")],
    )
    # the same shape with LF, so a CRLF-only failure is distinguishable from a
    # blank-line-in-gap failure
    SPILL_SHAPES[f"blank-in-gap-{_flavour}"] = (
        _entry(_flavour, f"bg{_flavour[:2]}", "3.0.0", gap=1, blank_in_gap=True),
        [_dep(f"bg{_flavour[:2]}", "3.0.0")],
    )
    # the widest entry the bound still resolves ...
    SPILL_SHAPES[f"at-bound-{_flavour}"] = (
        _entry(_flavour, f"ab{_flavour[:2]}", "1.0.0", gap=WINDOW_BOUND - 1),
        [_dep(f"ab{_flavour[:2]}", "1.0.0")],
    )
    # ... and one line past it, which is NOT seen. A real limitation, so it is asserted
    # rather than left to be discovered; test_no_extra_dependencies turns it into a
    # failure if a real entry ever grows this wide.
    SPILL_SHAPES[f"past-bound-{_flavour}"] = (
        _entry(_flavour, f"pb{_flavour[:2]}", "1.0.0", gap=WINDOW_BOUND + 1),
        [],
    )

    # Past the bound in the FIRST gap only. Each window is bounded separately, so a
    # fixture that pads every gap would still be blocked by a later one and would not
    # notice the first window losing its bound.
    SPILL_SHAPES[f"past-bound-first-gap-{_flavour}"] = (
        _entry(_flavour, f"pf{_flavour[:2]}", "1.0.0", gap=WINDOW_BOUND + 1, gaps=(0,)),
        [],
    )

# The same coverage for the reversed field order, so the second matchString's own
# windows are bounded and CRLF-tolerant by test, not only by the first string.
SPILL_SHAPES["at-bound-reversed"] = (
    _reversed_entry("abrv", "1.0.0", WINDOW_BOUND - 1),
    [("abrv", "https://charts.example.org/abrv", "1.0.0", "helm")],
)
SPILL_SHAPES["past-bound-reversed"] = (
    _reversed_entry("pbrv", "1.0.0", WINDOW_BOUND + 1),
    [],
)
SPILL_SHAPES["crlf-reversed"] = (
    _reversed_entry("crrv", "4.0.0", 1, eol="\r\n", blank_in_gap=True),
    [("crrv", "https://charts.example.org/crrv", "4.0.0", "helm")],
)


def test_window_does_not_cross_addon_blocks():
    """A line window must not step from one addon's block into the next one's fields.

    With an unbounded window the https manager walked from ``s3-chart`` to ``foo``'s
    repository and version, ate the text of the real ``foo`` and ``baz`` pins, and
    produced a dependency for a chart that never had that version. Each manager has
    its own window, so each is given its own shape here; the ``comment`` case covers
    the other direction, a window too strict to step over a column-0 comment.
    """
    rel = "gitops/addons/registry/synthetic.yaml"
    for shape, (text, want) in SPILL_SHAPES.items():
        got = sorted(_deps_in_text(text, rel))
        assert got == sorted(want), (
            f"shape {shape!r}: window crossed a block boundary or dropped a pin\n"
            f"  unexpected: {sorted(set(got) - set(want))}\n"
            f"  missing:    {sorted(set(want) - set(got))}"
        )


def test_window_does_not_backtrack_catastrophically():
    """A failed match must not cost more than linear time in the entry's size.

    Each window can consume a newline, and so can a `\\s*` written next to one, so an
    entry that never completes made the engine retry every split of the whitespace in
    every gap at once. With three windows that is cubic: the 260-character entry below
    took 24 s with those `\\s*` restored, against a median of 0.001 ms as shipped.
    Nothing about the extracted set changes either way, so no other test here can see
    it -- hence a time budget.
    """
    import time

    gap = "\n" * 39
    text = (
        "victim:\n"
        "  chartName: vc\n" + gap +
        "  chartNamespace: aws-controllers-k8s\n" + gap +
        "  chartRepository: public.ecr.aws\n" + gap +
        "  releaseName: deliberately-no-default-version\n"
    )
    started = time.monotonic()
    deps = _deps_in_text(text, "gitops/addons/registry/synthetic.yaml")
    elapsed = time.monotonic() - started
    assert deps == [], f"an entry with no defaultVersion must yield nothing, got {deps}"
    # The fixed patterns do this in single-digit milliseconds; the regression took
    # tens of seconds. A 5 s budget separates the two without being flaky on a loaded
    # host.
    assert elapsed < 5, (
        f"matching a {len(text)}-character entry took {elapsed:.1f}s: a window and an "
        "adjacent whitespace class are both consuming newlines again"
    )


def test_window_bound_is_the_one_the_fixtures_assume():
    """The fixtures pad to WINDOW_BOUND, so the config has to use the same number.

    Reading the bound out of renovate.json instead would make every fixture regenerate
    with it, so narrowing a window would silently pass its own test. Stating the number
    here and comparing keeps a config change visible, and it also catches a window
    that lost its bound entirely (`)*?` rather than `){0,N}?`).
    """
    bounds = _registry_window_bounds()
    assert bounds == {str(WINDOW_BOUND)}, (
        f"the registry managers' windows are bounded {sorted(bounds)}, but the fixtures "
        f"in this file are built for {WINDOW_BOUND}. Change both together, or the "
        "at-bound and past-bound shapes stop meaning anything."
    )
