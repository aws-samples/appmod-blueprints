# outputs.tf in your module directory

output "db_secret_arn" {
  description = "The ARN of the database credentials secret"
  value       = aws_secretsmanager_secret.db_credentials.arn
}

output "db_secret_name" {
  description = "The name of the database credentials secret"
  value       = aws_secretsmanager_secret.db_credentials.name
}

output "db_secret_version_id" {
  description = "The version ID of the database credentials secret"
  value       = data.aws_secretsmanager_secret_version.db_credentials.version_id
}

output "db_connection_string" {
  description = "The connection string for the database"
  value       = "postgresql://${local.db_creds.username}:${local.db_creds.password}@${aws_rds_cluster.rds_cluster_mod_engg_wksp.endpoint}:${aws_rds_cluster.rds_cluster_mod_engg_wksp.port}/${aws_rds_cluster.rds_cluster_mod_engg_wksp.database_name}"
  sensitive   = true
}

output "rds_cluster_endpoint" {
  description = "The cluster endpoint for the RDS cluster"
  value       = aws_rds_cluster.rds_cluster_mod_engg_wksp.endpoint
}

output "rds_cluster_port" {
  description = "The port for the RDS cluster"
  value       = aws_rds_cluster.rds_cluster_mod_engg_wksp.port
}
