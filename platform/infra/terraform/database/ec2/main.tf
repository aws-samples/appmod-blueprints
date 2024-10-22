variable "vpc_id" {}
variable "subnet_id" {}
variable "vpc_cidr" {}
variable "name_prefix" {}
variable "key_name" {}

resource "aws_security_group" "ec2_sg" {
  name        = "${var.name_prefix}ec2_sql_server_sg"
  description = "Security group for EC2 SQL Server instance"
  vpc_id      = var.vpc_id

  ingress {
    description = "RDP from VPC"
    from_port   = 3389
    to_port     = 3389
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.name_prefix}-ec2_sql_server_sg"
  }
}

resource "random_integer" "suffix" {
  min = 1000
  max = 9999
}

resource "aws_secretsmanager_secret" "ec2_credentials" {
  name = "mod-engg-workshop-ec2-credentials-${random_integer.suffix.result}"
}

resource "random_password" "ec2_password" {
  length           = 16
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "aws_secretsmanager_secret_version" "ec2_credentials" {
  secret_id = aws_secretsmanager_secret.ec2_credentials.id
  secret_string = jsonencode({
    username = "Administrator"
    password = random_password.ec2_password.result
  })
}

resource "aws_instance" "sql_server_instance" {
  ami           = "ami-034e95056cd0531b9"
  instance_type = "c5.2xlarge"
  subnet_id     = var.subnet_id

  vpc_security_group_ids = [aws_security_group.ec2_sg.id]

  root_block_device {
    volume_type = "gp3"
    volume_size = 100
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    instance_metadata_tags      = "enabled"
  }

  user_data = <<-EOF
              <powershell>
              # Set Administrator password
                #$password = (Get-SECSecretValue -SecretId ${aws_secretsmanager_secret.ec2_credentials.id}).SecretString | ConvertFrom-Json
                #net user Administrator $password.password
                #"Set-ExecutionPolicy Unrestricted -force\n"

              # Installing AWS CLI. We can directly provide the msi URL path to msiexec
                $installer="https://awscli.amazonaws.com/AWSCLIV2.msi";
                $logFolder=GetLogFolder -Name "AWSCLIV2";

                WriteLog -Message "Installing $($installer) ...";
                Start-Process -FilePath "C:\Windows\System32\msiexec.exe" -ArgumentList " /i $installer /passive  /norestart /log `"$($logFolder)awscli.txt`" " -Wait;
                WriteLog -Message "Done installing $($installer)";

              # Install EC2 Instance Connect
                $url = "https://s3.amazonaws.com/ec2-windows-ec2instanceconnect/EC2-Windows-EC2InstanceConnect.zip"
                Invoke-WebRequest -Uri $url -OutFile "C:\EC2-Windows-EC2InstanceConnect.zip"
                Expand-Archive -Path "C:\EC2-Windows-EC2InstanceConnect.zip" -DestinationPath "C:\EC2-Windows-EC2InstanceConnect"
                Start-Process -FilePath "C:\EC2-Windows-EC2InstanceConnect\install.ps1" -Wait

              # Install JRE
                $jreUrl = "https://javadl.oracle.com/webapps/download/AutoDL?BundleId=246474_2dee051a5d0647d5be72a7c0abff270e"
                Invoke-WebRequest -Uri $jreUrl -OutFile "C:\jre-installer.exe"
                Start-Process -FilePath "C:\jre-installer.exe" -ArgumentList "/s" -Wait

              # Install Babelfish Compass
                $babelfishReleaseUrl = "https://api.github.com/repos/babelfish-for-postgresql/babelfish_compass/releases/latest"
                $latestRelease = Invoke-RestMethod -Uri $babelfishReleaseUrl
                $zipAsset = $latestRelease.assets | Where-Object { $_.name -match "^BabelfishCompass_[a-zA-Z0-9]+(-[a-zA-Z0-9]+)?\.zip$" } | Select-Object -First 1
                Invoke-WebRequest -Uri $zipAsset.browser_download_url -OutFile "C:\BabelfishCompass.zip"
                Expand-Archive -Path "C:\BabelfishCompass.zip" -DestinationPath "C:\BabelfishCompass"
              
              # Create Northwind database and admin role
                $sqlCommand = @"
                CREATE DATABASE Northwind;
                GO
                USE Northwind;
                GO
                CREATE LOGIN AdminUser WITH PASSWORD = '$(ConvertFrom-SecureString -SecureString $password -AsPlainText)';
                GO
                CREATE USER AdminUser FOR LOGIN AdminUser;
                GO
                ALTER ROLE db_owner ADD MEMBER AdminUser;
                GO
                "@

                $sqlCommand | sqlcmd -S localhost

                # Update Secrets Manager with the new admin user
                $adminCredentials = @{
                    username = "AdminUser"
                    password = $(ConvertFrom-SecureString -SecureString $password -AsPlainText)
                }
                $adminCredentialsJson = $adminCredentials | ConvertTo-Json -Compress
                aws secretsmanager put-secret-value --secret-id ${aws_secretsmanager_secret.ec2_credentials.id} --secret-string $adminCredentialsJson
                
              </powershell>
              EOF

  tags = {
    Name = "${var.name_prefix}-sql_server_instance"
  }
}
