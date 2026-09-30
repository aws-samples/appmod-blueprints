#!/usr/bin/env python3
"""
skills-mcp — a FastMCP (StreamableHTTP) server that exposes the PEEKS/APEX
knowledge base (the appmod-blueprints `.kiro/skills` + `.kiro/steering` corpus)
to the OAP agent as callable MCP tools.

The corpus is BAKED INTO THE IMAGE at build time (COPY ./payload) so the server
has no runtime dependency on the repo. Refresh = rebuild the image via
generate.sh (which re-copies the current .kiro corpus).

Tools:
  - list_skills()                -> [{name, description}]
  - get_skill(name)              -> full SKILL.md (+ referenced files index)
  - get_skill_file(name, path)   -> a referenced file inside a skill (references/**, agents/**)
  - search_skills(query)         -> skills+steering whose text matches
  - list_steering()              -> [{name, title}]
  - get_steering(name)           -> full steering guide markdown

Transport: StreamableHTTP on :8000 (FastMCP default), matching the mcp-server
OAM component (port 8000, appProtocol agentgateway.dev/mcp).
"""
import os
import re

from fastmcp import FastMCP

PAYLOAD = os.getenv("PAYLOAD_DIR", "/payload")
SKILLS_DIR = os.path.join(PAYLOAD, "skills")
STEERING_DIR = os.path.join(PAYLOAD, "steering")

# stateless streamable-http: no persistent session/SSE GET stream (see run() below).
mcp = FastMCP("skills")


def _read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _skill_description(text: str) -> str:
    m = re.search(r"^description:\s*(.+)$", text, flags=re.MULTILINE)
    if m:
        return m.group(1).strip().strip('"')
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith("#") and not s.startswith("---"):
            return s[:200]
    return ""


@mcp.tool()
def list_skills() -> list[dict]:
    """List every available skill (name + one-line description). Call this first
    to discover which skill's method to load for a task (e.g. eks-recon)."""
    out = []
    if not os.path.isdir(SKILLS_DIR):
        return out
    for name in sorted(os.listdir(SKILLS_DIR)):
        skill_md = os.path.join(SKILLS_DIR, name, "SKILL.md")
        if os.path.isfile(skill_md):
            out.append({"name": name, "description": _skill_description(_read(skill_md))})
    return out


@mcp.tool()
def get_skill(name: str) -> str:
    """Return the full SKILL.md (the step-by-step method) for a skill, plus an
    index of its referenced files. Load this before executing a skill's workflow."""
    base = os.path.join(SKILLS_DIR, name)
    skill_md = os.path.join(base, "SKILL.md")
    if not os.path.isfile(skill_md):
        return f"ERROR: no such skill '{name}'. Call list_skills() for valid names."
    body = _read(skill_md)
    refs = []
    for root, _dirs, files in os.walk(base):
        for f in files:
            if f == "SKILL.md":
                continue
            rel = os.path.relpath(os.path.join(root, f), base)
            refs.append(rel)
    if refs:
        body += "\n\n---\nReferenced files (fetch with get_skill_file):\n" + \
                "\n".join(f"- {r}" for r in sorted(refs))
    return body


@mcp.tool()
def get_skill_file(name: str, path: str) -> str:
    """Return a referenced file inside a skill (e.g. references/foo.md, agents/bar.md).
    `path` must be one of the entries listed at the end of get_skill(name)."""
    base = os.path.realpath(os.path.join(SKILLS_DIR, name))
    target = os.path.realpath(os.path.join(base, path))
    # path-traversal guard
    if not target.startswith(base + os.sep):
        return "ERROR: path escapes the skill directory."
    if not os.path.isfile(target):
        return f"ERROR: no such file '{path}' in skill '{name}'."
    return _read(target)


@mcp.tool()
def search_skills(query: str) -> list[dict]:
    """Full-text search across all skills and steering guides. Returns matching
    docs with a short snippet, so you can decide what to load in full."""
    q = query.lower().strip()
    hits = []
    for kind, root in (("skill", SKILLS_DIR), ("steering", STEERING_DIR)):
        if not os.path.isdir(root):
            continue
        if kind == "skill":
            for name in sorted(os.listdir(root)):
                p = os.path.join(root, name, "SKILL.md")
                if os.path.isfile(p):
                    t = _read(p)
                    if q in t.lower():
                        idx = t.lower().find(q)
                        hits.append({"kind": kind, "name": name,
                                     "snippet": " ".join(t[max(0, idx - 80):idx + 120].split())})
        else:
            for f in sorted(os.listdir(root)):
                if f.endswith(".md"):
                    t = _read(os.path.join(root, f))
                    if q in t.lower():
                        idx = t.lower().find(q)
                        hits.append({"kind": kind, "name": f[:-3],
                                     "snippet": " ".join(t[max(0, idx - 80):idx + 120].split())})
    return hits


@mcp.tool()
def list_steering() -> list[dict]:
    """List the PEEKS platform steering guides (name + title)."""
    out = []
    if not os.path.isdir(STEERING_DIR):
        return out
    for f in sorted(os.listdir(STEERING_DIR)):
        if not f.endswith(".md"):
            continue
        t = _read(os.path.join(STEERING_DIR, f))
        title = f[:-3]
        for line in t.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        out.append({"name": f[:-3], "title": title})
    return out


@mcp.tool()
def get_steering(name: str) -> str:
    """Return the full text of a PEEKS steering guide (see list_steering for names)."""
    p = os.path.join(STEERING_DIR, name + ".md")
    if not os.path.isfile(p):
        return f"ERROR: no such steering guide '{name}'. Call list_steering() for valid names."
    return _read(p)


if __name__ == "__main__":
    # stateless_http + json_response passed to run(): each POST is self-contained,
    # no long-lived SSE GET stream for the L7 proxy (agentgateway) to close. In
    # stateful mode the Strands MCP client's standalone GET stream was cut
    # ("upstream stream ended unexpectedly") and the client discarded the tools.
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        stateless_http=True,
        json_response=True,
    )
