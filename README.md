# Modern Engineering on AWS

This repository is the main solution repository for the Modern Engineering on AWS initiative. It contains a comprehensive set of application modernization blueprints and patterns that cover various aspects of modern cloud-native development and operations on AWS.

## Overview

Modern Engineering on AWS is an initiative aimed at providing developers and organizations with best practices, patterns, and blueprints for building and managing modern applications on the AWS cloud platform. This repository serves as a central resource for implementing cutting-edge engineering practices in cloud environments.

## Key Features

- **Platform Engineering**: Blueprints and patterns for setting up robust, scalable platform infrastructure on AWS.
- **Application Deployment**: Best practices and tools for efficient and reliable application deployment processes.
- **GitOps**: Implementations of GitOps principles for managing infrastructure and applications as code.
- **KubeVela**: Integration patterns and examples using KubeVela for application delivery and management.
- **Progressive Delivery**: Strategies and implementations for gradual rollouts and feature flagging.

## Application Blueprints

Our repository includes various application blueprints that demonstrate modern engineering practices. These blueprints cover:

1. Microservices architectures
2. Serverless applications
3. Containerized applications
4. Event-driven architectures
5. CI/CD pipelines

Each blueprint provides a detailed walkthrough of the architecture, implementation details, and best practices.

## Getting Started

To get started with Modern Engineering on AWS:

1. Clone this repository
2. Provision the platform that consists of the management cluster and two workloads clusters that represent dev and prod environments. The environments can be customized based on the customer needs.
3. Navigate to the specific tech or pattern you're interested in, e.g platform/backstage, platform/crossplane, platform/components (or traits).
4. Follow the README instructions in each subdirectory for detailed setup and usage guidelines

## Helm Chart Dependencies

This repository uses Taskfile to automate Helm chart dependency management. Available tasks:

```bash
# Check which charts have dependencies and their status
task check-helm-dependencies

# Build all Helm chart dependencies automatically
task build-helm-dependencies

# Clean all generated dependency files
task clean-helm-dependencies
```

**Note:** Run `task build-helm-dependencies` when:
- Setting up the repository for the first time
- Adding new charts with dependencies
- Updating dependency versions in Chart.yaml files

The task automatically handles adding required Helm repositories and building dependencies for flux, crossplane, and kubevela charts.

## Contributing

We welcome contributions to the Modern Engineering on AWS initiative. Please read our [CONTRIBUTING](CONTRIBUTING.md) guide for details on our code of conduct and the process for submitting pull requests.

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information on reporting security issues.

## License

This library is licensed under the MIT-0 License. See the LICENSE file for details.

## Contact

For any questions or feedback regarding Modern Engineering on AWS, please open an issue in this repository.

