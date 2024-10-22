# Terraform AWS Infrastructure Project

This project uses Terraform to deploy a multi-tier infrastructure on AWS, including a VPC, Aurora PostgreSQL database, and an EC2 instance running Windows with SQL Server for Modern Engineering Workshop.

## Project Overview

This project sets up the following resources:
- EC2 instance with SQL Server
- Security group for the EC2 instance
- AWS Secrets Manager secret for storing credentials
- SSH key pair for instance access

The EC2 instance is configured with:
- SQL Server
- AWS CLI
- EC2 Instance Connect
- Java Runtime Environment (JRE)
- Babelfish Compass

Additionally, it creates a new database named "Northwind" and sets up an admin user.

## Project Structure

.
├── dev-main.tf
|-- prod-main.tf
├─ variables.tf
├── providers.tf
├── vpc/
│ ├── main.tf
│ └── variables.tf
├── aurora/
│ ├── main.tf
│ └── variables.tf
└── ec2/
├── main.tf
└── variables.tf

## Prerequisites

Before you begin, ensure you have:
- [Terraform](https://www.terraform.io/downloads.html) installed (version 0.12+)
- AWS CLI configured with appropriate credentials
- An existing VPC and subnet in your AWS account
- An SSH key pair created in AWS

## Modules

### VPC Module

Located in the `vpc/` directory, this module:
- Creates a new VPC or uses an existing one based on input
- Sets up subnets in specified availability zones
- Outputs VPC ID, subnet IDs, and VPC CIDR

### Aurora Module

Located in the `aurora/` directory, this module:
- Creates an Aurora PostgreSQL cluster with Babelfish enabled
- Sets up necessary security groups and parameter groups
- Manages database credentials using AWS Secrets Manager

### EC2 Module

Located in the `ec2/` directory, this module:
- Deploys a Windows EC2 instance with SQL Server
- Installs additional software like EC2 Instance Connect, JRE, and Babelfish Compass
- Manages instance credentials using AWS Secrets Manager

## Usage

1. Clone this repository
2. Configure your AWS credentials (see "AWS Credentials" section below)
3. Modify `variables.tf` in the root directory to set your desired values
4. Run `terraform init` to initialize Terraform
5. Run `terraform plan` to see the execution plan
6. Run `terraform apply -var="key_name=my-key-pair.pem"` to create the infrastructure

## Variables

Key variables in `variables.tf`:

- `vpc_id`: Existing VPC ID (optional)
- `vpc_cidr`: CIDR block for the VPC
- `name_prefix`: Prefix for resource names
- `availability_zones`: List of availability zones
- `db_username`: Username for the Aurora database
- `aws_region`: AWS region to deploy resources
- `key_name` : "my-key-pair"

## AWS Credentials

Ensure your AWS credentials are properly configured. You can do this by:

1. Setting environment variables:

export AWS_ACCESS_KEY_ID="your_access_key"
export AWS_SECRET_ACCESS_KEY="your_secret_key"
export AWS_REGION="your_preferred_region"


2. Using AWS CLI: Run `aws configure`

3. Using a shared credentials file at `~/.aws/credentials`

## Important Notes

- The EC2 instance is configured with RDP access from within the VPC
- Database credentials are stored in AWS Secrets Manager
- Ensure you have necessary permissions to create all resources

## Cleanup

To remove all created resources, run:

`terraform destroy`

Confirm the action when prompted.

## Contributing

Feel free to submit issues or pull requests if you have suggestions for improvements or find any bugs.
