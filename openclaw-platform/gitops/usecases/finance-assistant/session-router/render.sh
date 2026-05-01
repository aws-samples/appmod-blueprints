#!/usr/bin/env bash
# Inlines session-router/server.js and package.json into the deployment
# manifest's ConfigMaps. Output: k8s/deployment.rendered.yaml — apply that
# (or `kubectl apply -f`) rather than the raw template.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src="${here}/server.js"
pkg="${here}/package.json"
tpl="${here}/k8s/deployment.yaml"
out="${here}/k8s/deployment.rendered.yaml"

[ -f "$src" ] || { echo "missing $src" >&2; exit 1; }
[ -f "$pkg" ] || { echo "missing $pkg" >&2; exit 1; }
[ -f "$tpl" ] || { echo "missing $tpl" >&2; exit 1; }

# awk -v chokes on multi-line strings; drive the two replacements by
# reading the marker line and streaming the file in its place.
python3 - "$tpl" "$src" "$pkg" "$out" <<'PY'
import sys, pathlib
tpl, src, pkg, out = (pathlib.Path(p) for p in sys.argv[1:5])
src_body = "\n".join("    " + line for line in src.read_text().splitlines())
pkg_body = "\n".join("    " + line for line in pkg.read_text().splitlines())
result = []
for line in tpl.read_text().splitlines():
    if line.strip() == "REPLACE_WITH_ROUTER_SERVER_JS":
        result.append(src_body); continue
    if line.strip() == "REPLACE_WITH_PACKAGE_JSON":
        result.append(pkg_body); continue
    result.append(line)
out.write_text("\n".join(result) + "\n")
PY

echo "wrote $out"
