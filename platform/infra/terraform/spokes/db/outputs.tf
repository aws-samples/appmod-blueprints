output "aurora_db_secret_arn" {
  description = "ARN of the Aurora database secret"
  value       = module.aurora.db_secret_arn
}

output "aurora_db_secret_name" {
  description = "Name of the Aurora database secret"
  value       = module.aurora.db_secret_name
}

output "aurora_db_secret_version_id" {
  description = "Version ID of the Aurora database secret"
  value       = module.aurora.db_secret_version_id
}

output "aurora_db_connection_string" {
  description = "Connection string for the Aurora database"
  value       = module.aurora.db_connection_string
  sensitive   = true
}

output "aurora_cluster_endpoint" {
  description = "Aurora cluster endpoint"
  value       = module.aurora.rds_cluster_endpoint
}

output "aurora_cluster_port" {
  description = "Aurora cluster port"
  value       = module.aurora.rds_cluster_port
}

output "ec2_instance_id" {
  description = "ID of the EC2 instance"
  value       = module.ec2.instance_id
}

output "ec2_instance_public_ip" {
  description = "Public IP of the EC2 instance"
  value       = module.ec2.instance_public_ip
}

output "ec2_instance_private_ip" {
  description = "Private IP of the EC2 instance"
  value       = module.ec2.instance_private_ip
}

output "ec2_security_group_id" {
  description = "Security group ID of the EC2 instance"
  value       = module.ec2.security_group_id
}

output "ec2_credentials_secret_arn" {
  description = "ARN of the EC2 credentials secret"
  value       = module.ec2.ec2_credentials_secret_arn
}

output "ec2_credentials_secret_name" {
  description = "Name of the EC2 credentials secret"
  value       = module.ec2.ec2_credentials_secret_name
}
