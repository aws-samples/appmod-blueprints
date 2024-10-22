variable "vpc_id" {}
variable "subnet_ids" {}
variable "vpc_cidr" {}
variable "name_prefix" {}
variable "db_username" {}
variable "availability_zones" {
    description = "List of availability zones"
    type        = list(string)
  }
  

resource "aws_db_subnet_group" "rds_cluster_mod_engg_wksp_sng" {
  name       = "${var.name_prefix}mod_engg_wksp-db-subnet"
  subnet_ids = var.subnet_ids

  tags = {
    Application = "MODERN ENGG WORKSHOP DATABASE"
    Provider    = "mod_engg_wksp"
    Name = "${var.name_prefix}mod-engg-wksp-aurora-subnet-group"
  }
}

resource "aws_security_group" "rds_mod_engg_wksp_sg" {
  name        = "${var.name_prefix}rds_mod_engg_wksp_sg"
  description = "Modern Engg Workshop Database Access"
  vpc_id      = var.vpc_id

  tags = {
    Name = "${var.name_prefix}rds_mod_engg_wksp_sg"
  }
}

resource "aws_security_group_rule" "rds_mod_engg_wksp_psql_inbound" {
  security_group_id = aws_security_group.rds_mod_engg_wksp_sg.id
  description       = "Ingress PostgreSQL traffic"
  type              = "ingress"
  from_port         = 5432
  to_port           = 5432
  protocol          = "tcp"
  cidr_blocks       = [var.vpc_cidr]
}

resource "aws_security_group_rule" "rds_mod_engg_wksp_babelfish_inbound" {
  security_group_id = aws_security_group.rds_mod_engg_wksp_sg.id
  description       = "Ingress Babelfish traffic"
  type              = "ingress"
  from_port         = 1433
  to_port           = 1433
  protocol          = "tcp"
  cidr_blocks       = [var.vpc_cidr]
}

resource "aws_rds_cluster_parameter_group" "rds_mod_engg_wksp_pg" {
  name   = "${var.name_prefix}mod-engg-wksp-pg"
  family = "aurora-postgresql16"

  parameter {
    name         = "rds.babelfish_status"
    value        = "on"
    apply_method = "pending-reboot"
  }

  tags = {
    Application = "MODERN ENGG WORKSHOP DATABASE"
    Provider    = "mod_engg_wksp"
  }
}

resource "random_integer" "suffix" {
  min = 1000
  max = 9999
}

resource "aws_secretsmanager_secret" "db_credentials" {
  name = "mod-engg-workshop-db-credentials-${random_integer.suffix.result}"
}

resource "random_password" "db_password" {
  length           = 16
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "aws_secretsmanager_secret_version" "db_credentials_initial" {
    secret_id     = aws_secretsmanager_secret.db_credentials.id
    secret_string = jsonencode({
      username = var.db_username
      password = random_password.db_password.result
    })
  }
  
data "aws_secretsmanager_secret_version" "db_credentials" {
    secret_id  = aws_secretsmanager_secret.db_credentials.id
    depends_on = [aws_secretsmanager_secret_version.db_credentials_initial]
  }

locals {
    db_creds = jsondecode(data.aws_secretsmanager_secret_version.db_credentials.secret_string)
  }

locals {
    # Use up to 3 AZs for the Aurora cluster
    aurora_azs = slice(var.availability_zones, 0, min(length(var.availability_zones), 3))
  }
  
resource "aws_rds_cluster" "rds_cluster_mod_engg_wksp" {
  cluster_identifier = "${var.name_prefix}mod-engg-wksp"
  availability_zones = local.aurora_azs

  engine         = "aurora-postgresql"
  engine_mode    = "provisioned"
  engine_version = "16.3"

  database_name   = "NorthWind"
  master_username = local.db_creds.username
  master_password = local.db_creds.password

  backup_retention_period = 3
  copy_tags_to_snapshot   = true

  db_cluster_parameter_group_name = aws_rds_cluster_parameter_group.rds_mod_engg_wksp_pg.name
  db_subnet_group_name            = aws_db_subnet_group.rds_cluster_mod_engg_wksp_sng.name
  deletion_protection             = false
  enabled_cloudwatch_logs_exports = ["postgresql"]

  skip_final_snapshot       = true
  final_snapshot_identifier = "mod-engg-wksp-cluster-final-snapshot"

  iam_database_authentication_enabled = false

  preferred_backup_window      = "23:00-00:00"
  preferred_maintenance_window = "sun:01:00-sun:02:00"

  vpc_security_group_ids = [aws_security_group.rds_mod_engg_wksp_sg.id]

  tags = {
    Application = "MODERN ENGG WORKSHOP DATABASE"
    Provider    = "mod_engg_wksp"
  }
}

resource "aws_rds_cluster_instance" "rds_cluster_mod_engg_wksp_writer" {
  cluster_identifier = aws_rds_cluster.rds_cluster_mod_engg_wksp.id
  instance_class     = "db.r6g.2xlarge"
  identifier         = "${var.name_prefix}mod-engg-wksp-writer"

  engine         = aws_rds_cluster.rds_cluster_mod_engg_wksp.engine
  engine_version = aws_rds_cluster.rds_cluster_mod_engg_wksp.engine_version

  auto_minor_version_upgrade  = true
  copy_tags_to_snapshot       = true
  db_subnet_group_name        = aws_db_subnet_group.rds_cluster_mod_engg_wksp_sng.name
  monitoring_interval         = 0
  performance_insights_enabled = true
  preferred_maintenance_window = "sun:01:00-sun:02:00"
  publicly_accessible         = false

  tags = {
    Application = "MODERN ENGG WORKSHOP DATABASE"
    Provider    = "mod_engg_wksp"
  }
}


resource "aws_cloudwatch_log_group" "rds_cluster_mod_engg_wksp_lg" {
  name              = "/aws/rds/cluster/${aws_rds_cluster.rds_cluster_mod_engg_wksp.cluster_identifier}-${random_integer.suffix.result}/postgresql"
  retention_in_days = 60
}

resource "aws_secretsmanager_secret_version" "db_credentials_updated" {
    secret_id = aws_secretsmanager_secret.db_credentials.id
    secret_string = jsonencode({
      username        = var.db_username
      password        = random_password.db_password.result
      engine          = "aurora-postgresql"
      host            = aws_rds_cluster.rds_cluster_mod_engg_wksp.endpoint
      port            = aws_rds_cluster.rds_cluster_mod_engg_wksp.port
      dbClusterIdentifier = aws_rds_cluster.rds_cluster_mod_engg_wksp.cluster_identifier
      dbname          = aws_rds_cluster.rds_cluster_mod_engg_wksp.database_name
    })
  }
  
  