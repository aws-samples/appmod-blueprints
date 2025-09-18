################################################################################
# Security Groups for Ingress Nginx
################################################################################

# Security group for HTTP access (port 80)
resource "aws_security_group" "ingress_http" {
  name        = "${local.name}-ingress-http"
  description = "HTTP from anywhere"
  vpc_id      = module.vpc.vpc_id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTP from anywhere"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.tags, {
    Name = "${local.name}-ingress-http"
  })
}

# Security group for HTTPS access (port 443)
resource "aws_security_group" "ingress_https" {
  name        = "${local.name}-ingress-https"
  description = "HTTPS from anywhere"
  vpc_id      = module.vpc.vpc_id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTPS from anywhere"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.tags, {
    Name = "${local.name}-ingress-https"
  })
}
