"""Hermetic tests for the temporary files of backstage_get_token
(scripts/validation/backstage-auth.sh).

The login used to write its steps to four fixed files (/tmp/_bs_s2.txt, _bs_s3.txt,
_bs_s4.txt, _bs_frame.txt), so two overlapping calls on one host overwrote each other's
files and the first call's EXIT trap deleted the second's. Each call now writes into its
own `mktemp -d` directory, removed whole by the EXIT trap. These tests pin that:

1. every login file is written under a private, mode-0700 `$TMPDIR/backstage-auth.*`
   directory, a new one per call, and nothing is left in TMPDIR afterwards;
2. four calls whose login steps overlap each get their own token;
3. when `mktemp -d` fails (or returns nothing, or returns a regular file), the call stops
   before the first login request, including where set -e is ignored (sourced `if`,
   backstage_template_status's `|| true`), so nothing is written at the filesystem root;
4. a TMPDIR that contains a space or a quote still gives the token and is left empty
   (the frame path is passed to python quoted, and the trap quotes both paths).

The fake curl writes the step files the helper expects, logs every -D/-o path with the
mode of its directory, and returns the token in $FAKE_TOK. With FAKE_BARRIER=N it waits,
after writing the frame, until N calls have written theirs, so the overlap is certain.

Run:  python -m pytest workshop/scripts/tests/test_backstage_auth_tmpdir.py -q
"""
import os
import re
import shutil
import subprocess

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
BSAUTH = os.path.join(REPO, "scripts", "validation", "backstage-auth.sh")
REAL_MKTEMP = shutil.which("mktemp")
ZSH = shutil.which("zsh")

FAKE_CURL = r'''#!/usr/bin/env bash
out="" hdr="" auth="" url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift ;;
    -D) hdr="$2"; shift ;;
    -H) case "$2" in Authorization:*) auth="$2" ;; esac; shift ;;
    https://*) url="$1" ;;
  esac
  shift
done
case "$url" in
  */api/catalog/*)
    printf '%s\n' "$auth" >> "$FAKE_T/catalog.log"
    case "$auth" in *"Bearer "?*) printf 200 ;; *) printf 401 ;; esac
    exit 0 ;;
esac
tok="${FAKE_TOK:-TOK}"
for p in "$hdr" "$out"; do
  if [ -n "$p" ] && [ "$p" != /dev/null ]; then
    printf '%s\t%s\n' "$p" "$(ls -ld "$(dirname "$p")" 2>/dev/null | cut -c1-10)" >> "$FAKE_T/paths.log"
  fi
done
case "$hdr" in
  *_bs_s2.txt) printf 'location: https://kc.example/auth\r\n' > "$hdr" 2>/dev/null || true ;;
  *_bs_s4.txt) printf 'location: https://bs.example/api/auth/keycloak-oidc/handler/frame\r\n' > "$hdr" 2>/dev/null || true ;;
esac
case "$out" in
  *_bs_s3.txt) echo '<form action="https://kc.example/login">' > "$out" 2>/dev/null || true ;;
  *_bs_frame.txt)
    echo "decodeURIComponent('%7B%22response%22%3A%7B%22backstageIdentity%22%3A%7B%22token%22%3A%22${tok}%22%7D%7D%7D')" > "$out" 2>/dev/null || true
    if [ -n "${FAKE_BARRIER:-}" ]; then
      : > "$FAKE_T/ready.$tok"
      i=0
      while [ "$(ls "$FAKE_T" | grep -c '^ready\.')" -lt "$FAKE_BARRIER" ] && [ $i -lt 200 ]; do
        sleep 0.05; i=$((i + 1))
      done
    fi ;;
esac
exit 0
'''

FAKE_MKTEMP = '''#!/usr/bin/env bash
case " $* " in
  *" -d "*)
    case "$FAKE_MKTEMP" in
      fail) exit 1 ;;
      empty) exit 0 ;;
      file) : > "$FAKE_T/not-a-dir"; echo "$FAKE_T/not-a-dir"; exit 0 ;;
    esac ;;
esac
exec "%s" "$@"
''' % REAL_MKTEMP

DIR_RE = r"backstage-auth\.[A-Za-z0-9]{6}"


def setup(tmp_path, tmpdir_name="tmp", mktemp_mode=None):
    b = tmp_path / "bin"
    b.mkdir()
    (b / "curl").write_text(FAKE_CURL)
    os.chmod(b / "curl", 0o755)
    if mktemp_mode:
        (b / "mktemp").write_text(FAKE_MKTEMP)
        os.chmod(b / "mktemp", 0o755)
    td = tmp_path / tmpdir_name
    td.mkdir()
    env = dict(os.environ, PATH=f"{b}:{os.environ['PATH']}", FAKE_T=str(tmp_path), TMPDIR=str(td),
               HOME=str(tmp_path), BACKSTAGE_URL="https://bs.example", USER1_PASSWORD="pw")
    if mktemp_mode:
        env["FAKE_MKTEMP"] = mktemp_mode
    return env, td


def logged(tmp_path):
    p = tmp_path / "paths.log"
    if not p.exists():
        return []
    return [tuple(line.split("\t")) for line in p.read_text().splitlines()]


def run_exec(env, **extra):
    return subprocess.run(["bash", BSAUTH], env=dict(env, **extra), capture_output=True, text=True, timeout=60)


def run_sourced(shell, env, expr='printf "tok=[%s]\\n" "$BS_TOKEN"'):
    return subprocess.run([shell, "-c", f'. "$1"; {expr}', "_", BSAUTH], env=env,
                          capture_output=True, text=True, timeout=60)


SHELLS = ["bash"] + (["zsh"] if ZSH else [])


def test_get_token_writes_only_under_private_tmpdir(tmp_path):
    env, td = setup(tmp_path)
    dirs = []
    for n in (1, 2):
        before = len(logged(tmp_path))
        r = run_exec(env)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "TOK"
        entries = logged(tmp_path)[before:]
        names = sorted(os.path.basename(p) for p, _ in entries)
        assert names == ["_bs_frame.txt", "_bs_s2.txt", "_bs_s3.txt", "_bs_s4.txt"], entries
        for p, mode in entries:
            assert re.fullmatch(re.escape(str(td)) + "/" + DIR_RE + r"/_bs_\w+\.txt", p), p
            assert mode == "drwx------", (p, mode)
        call_dirs = {os.path.dirname(p) for p, _ in entries}
        assert len(call_dirs) == 1, call_dirs
        dirs.append(call_dirs.pop())
        assert os.listdir(td) == [], f"call {n} left {os.listdir(td)}"
    assert dirs[0] != dirs[1], "two calls shared one directory"


def test_get_token_concurrent_calls_get_own_token(tmp_path):
    env, td = setup(tmp_path)
    toks = ["T1", "T2", "T3", "T4"]
    procs = [subprocess.Popen(["bash", BSAUTH], env=dict(env, FAKE_TOK=t, FAKE_BARRIER=str(len(toks))),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for t in toks]
    got = {}
    for t, p in zip(toks, procs):
        out, err = p.communicate(timeout=60)
        got[t] = (out.strip(), err.strip()[-300:])
    assert {t: v[0] for t, v in got.items()} == {t: t for t in toks}, got
    assert len({os.path.dirname(p) for p, _ in logged(tmp_path)}) == len(toks)
    assert os.listdir(td) == []


@pytest.mark.parametrize("mode", ["fail", "empty", "file"])
@pytest.mark.parametrize("shell", SHELLS)
def test_get_token_mktemp_d_failure_stops_before_curl_sourced(tmp_path, shell, mode):
    # Sourced: the source block calls the function in an `if` condition.
    env, td = setup(tmp_path, mktemp_mode=mode)
    r = run_sourced(shell, env)
    assert "backstage-auth: cannot create a temporary directory" in r.stderr, r.stderr
    assert "tok=[]" in r.stdout, r.stdout
    assert logged(tmp_path) == [], logged(tmp_path)
    assert os.listdir(td) == [], "cookie jar left behind"


@pytest.mark.parametrize("mode", ["fail", "empty", "file"])
def test_get_token_mktemp_d_failure_stops_before_curl_template_status(tmp_path, mode):
    # backstage_template_status calls the function with `|| true`: set -e is ignored there
    # in every shell, so only the explicit check keeps the files away from `/`.
    env, td = setup(tmp_path, mktemp_mode=mode)
    r = run_sourced("bash", env, "backstage_template_status")
    assert r.stdout.strip().splitlines()[-1] == "401", (r.stdout, r.stderr)
    assert logged(tmp_path) == [], logged(tmp_path)
    assert (tmp_path / "catalog.log").read_text().splitlines() == ["Authorization: Bearer "]
    assert os.listdir(td) == []


@pytest.mark.parametrize("name", ["with space", "a'b"])
@pytest.mark.parametrize("shell", SHELLS)
def test_get_token_tmpdir_with_space_or_quote(tmp_path, shell, name):
    env, td = setup(tmp_path, tmpdir_name=name)
    r = run_sourced(shell, env)
    assert "tok=[TOK]" in r.stdout, (r.stdout, r.stderr)
    assert len(logged(tmp_path)) == 4
    assert all(p.startswith(str(td) + "/") for p, _ in logged(tmp_path))
    assert os.listdir(td) == [], f"left {os.listdir(td)}"
