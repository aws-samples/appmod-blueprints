# outputs.tf in the EC2 module directory

output "instance_id" {
  description = "The ID of the EC2 instance"
  value       = aws_instance.sql_server_instance.id
}

output "instance_public_ip" {
  description = "The public IP address of the EC2 instance"
  value       = aws_instance.sql_server_instance.public_ip
}

output "instance_private_ip" {
  description = "The private IP address of the EC2 instance"
  value       = aws_instance.sql_server_instance.private_ip
}

output "security_group_id" {
  description = "The ID of the security group attached to the EC2 instance"
  value       = aws_security_group.ec2_sg.id
}

output "ec2_credentials_secret_arn" {
  description = "The ARN of the EC2 credentials secret"
  value       = aws_secretsmanager_secret.ec2_credentials.arn
}

output "ec2_credentials_secret_name" {
  description = "The name of the EC2 credentials secret"
  value       = aws_secretsmanager_secret.ec2_credentials.name
}
