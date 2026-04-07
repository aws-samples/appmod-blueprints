# rgd-authoring

Write ResourceGraphDefinitions (RGDs) for kro — the Kubernetes Resource Orchestrator.

## Why it exists

kro RGDs have specific syntax (SimpleSchema, CEL expressions, forEach collections, externalRef) and many constraints (naming rules, reserved keywords, dependency rules). This skill encodes all of that so the agent produces valid RGDs on the first try.

## How to use it

- "Create an RGD for a web app with Deployment, Service, and Ingress"
- "Write a kro ResourceGraphDefinition that provisions DynamoDB tables from a list"
- "Generate an instance for the WebPlatform RGD"
