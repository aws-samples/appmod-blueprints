# AWS Secrets Manager resources for the platform

# PostgreSQL password for Backstage application
resource "aws_secretsmanager_secret" "backstage_postgresql_password" {
  name                    = "${var.resource_prefix}-backstage-postgresql-password"
  description             = "PostgreSQL password for Backstage application"
  recovery_window_in_days = 0

  tags = {
    Application = "Backstage"
    Environment = "Platform"
    ManagedBy   = "Terraform"
    Purpose     = "Database Authentication"
  }
}

# Generate a random password for PostgreSQL
resource "random_password" "backstage_postgresql_password" {
  length  = 32
  special = true
  # Exclude characters that might cause issues in connection strings
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

# Store the password in AWS Secrets Manager
resource "aws_secretsmanager_secret_version" "backstage_postgresql_password" {
  secret_id = aws_secretsmanager_secret.backstage_postgresql_password.id
  secret_string = jsonencode({
    password = random_password.backstage_postgresql_password.result
  })
}

# Keycloak Admin Password
resource "aws_secretsmanager_secret" "keycloak_admin_password" {
  name                    = "${var.resource_prefix}-keycloak-admin-password"
  description             = "Keycloak admin password"
  recovery_window_in_days = 0

  tags = {
    Application = "Keycloak"
    Environment = "Platform"
    ManagedBy   = "Terraform"
    Purpose     = "Admin Authentication"
  }
}

# Keycloak admin password uses the consistent workshop password (ide_password)

resource "aws_secretsmanager_secret_version" "keycloak_admin_password" {
  secret_id = aws_secretsmanager_secret.keycloak_admin_password.id
  secret_string = jsonencode({
    password = var.ide_password
  })
}

# Keycloak Database Password
resource "aws_secretsmanager_secret" "keycloak_db_password" {
  name                    = "${var.resource_prefix}-keycloak-db-password"
  description             = "Keycloak database password"
  recovery_window_in_days = 0

  tags = {
    Application = "Keycloak"
    Environment = "Platform"
    ManagedBy   = "Terraform"
    Purpose     = "Database Authentication"
  }
}

resource "random_password" "keycloak_db_password" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "aws_secretsmanager_secret_version" "keycloak_db_password" {
  secret_id = aws_secretsmanager_secret.keycloak_db_password.id
  secret_string = jsonencode({
    password = random_password.keycloak_db_password.result
  })
}

# Keycloak User Password (for workshop users)
resource "aws_secretsmanager_secret" "keycloak_user_password" {
  name                    = "${var.resource_prefix}-keycloak-user-password"
  description             = "Keycloak user password for workshop participants"
  recovery_window_in_days = 0

  tags = {
    Application = "Keycloak"
    Environment = "Platform"
    ManagedBy   = "Terraform"
    Purpose     = "User Authentication"
  }
}

resource "random_password" "keycloak_user_password" {
  length  = 16
  special = false # User-friendly password for workshop participants
}

resource "aws_secretsmanager_secret_version" "keycloak_user_password" {
  secret_id = aws_secretsmanager_secret.keycloak_user_password.id
  secret_string = jsonencode({
    password = random_password.keycloak_user_password.result
  })
}
