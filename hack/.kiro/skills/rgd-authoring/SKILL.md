---
name: rgd-authoring
description: Write ResourceGraphDefinitions (RGDs) for kro. Use when user says "create RGD", "kro resource", "ResourceGraphDefinition", "define schema", "CEL expression", "external reference", "forEach collection", or wants to author kro CRDs. Do NOT use for deploying or troubleshooting existing kro resources — use research-question instead.
---

# RGD Authoring

## Overview

Authors ResourceGraphDefinitions for [kro](https://kro.run) — the Kubernetes Resource Orchestrator. Handles schema design, CEL expressions, resource dependencies, collections, external references, and instance generation.

## Prerequisites

**Constraints:**
- You MUST read `references/rgd-reference.md` before writing any RGD because it contains the complete syntax, rules, and constraints

## Parameters

- **mode** (optional, default: "rgd"): "rgd" (RGD only), "instance" (instance only), "both" (RGD + example instance)
- **resources** (required): What Kubernetes resources to orchestrate

## Workflow

### 1. Determine Output

Clarify what the user needs.

**Constraints:**
- If user asks for an RGD → output the ResourceGraphDefinition
- If user asks for an instance → find the existing RGD first, then output a matching instance
- If user asks for both → output both the RGD and an example instance
- If unclear, you MUST ask which they need

### 2. Gather Requirements

Understand what resources to orchestrate.

**Constraints:**
- You MUST know what Kubernetes resources to include before writing
- You SHOULD ask about: schema fields, conditional resources, collections, external references
- You MUST NOT guess resource apiVersions — verify against docs if unsure because wrong apiVersions cause silent failures

### 3. Write the RGD

Author the ResourceGraphDefinition YAML.

**Constraints:**
- You MUST follow all naming rules from the reference (lowerCamelCase IDs, PascalCase kind, no hyphens in IDs)
- You MUST NOT use reserved keywords as resource IDs because kro rejects them at creation time
- You MUST use `?` operator for fields with unknown structure (ConfigMap data, etc.)
- You MUST use inference profile syntax for status fields — status MUST reference at least one resource
- You MUST set `metadata.namespace` on namespaced child resources when `scope: Cluster`
- You SHOULD use `readyWhen` on resources that have meaningful readiness conditions
- You SHOULD order resource fields as: `id`, `forEach`, `readyWhen`, `includeWhen`, `template`/`externalRef`
- You MUST present YAML in code blocks with brief explanations for non-obvious choices

### 4. Validate

Review the RGD for common mistakes.

**Constraints:**
- You MUST check for circular dependencies between resources
- You MUST verify `readyWhen` only references self (or `each` for collections)
- You MUST verify `includeWhen` conditions return bool
- You MUST verify forEach iterators are lowerCamelCase and don't conflict with resource IDs
- You SHOULD check that string templates only contain string-returning expressions

## Examples

### Simple RGD

**Input:** "Create an RGD for a web app with Deployment + Service"

**Output:** RGD with schema (name, image, replicas, port), Deployment resource, Service resource referencing Deployment, status with availableReplicas and endpoint.

### RGD with Collection

**Input:** "Create an RGD that provisions multiple databases from a list"

**Output:** RGD with `databases: "[]DatabaseSpec"` in schema, forEach resource creating one PostgreSQL per entry, readyWhen checking each item's phase.
