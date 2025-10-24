# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Terraform-based AWS infrastructure demo that provisions a multi-environment setup running a Flask application in Docker on EC2 instances via Auto Scaling Groups. The infrastructure includes VPC, RDS MySQL database, ECR, Application Load Balancer, and automated CI/CD deployment through GitHub Actions.

## Development Commands

### Flask Application (apps/)
```powershell
# Run the Flask app locally
cd apps
python app.py

# Run unit tests
cd apps
python -m unittest test_app -v

# Run tests with pytest and coverage
cd apps
pip install pytest pytest-cov
pytest test_app.py -v --cov=app --cov-report=term-missing

# Build Docker image locally
docker build -t incode-demo-1-app:local .

# Run container locally
docker run -d -p 8080:8080 incode-demo-1-app:local
```

### Terraform Operations

#### Bootstrap (One-time setup)
```powershell
cd terraform/bootstrap
terraform init
terraform apply
```

#### Environment Deployment
```powershell
# Navigate to specific environment
cd terraform/aws/environments/dev/eu-central-1

# Initialize with remote backend
terraform init

# Validate configuration
terraform validate

# Plan with variable file
terraform plan -var-file=dev.tfvars

# Apply changes
terraform apply -var-file=dev.tfvars

# Destroy environment
terraform destroy -var-file=dev.tfvars
```

## Architecture Overview

### Infrastructure Flow
1. **VPC Module**: Creates VPC with public/private subnets, NAT gateways, and routing
2. **RDS Module**: Provisions MySQL 8.0 database with credentials stored in AWS Secrets Manager
3. **ECR Module**: Container registry for storing Flask app Docker images
4. **ALB Module**: Application Load Balancer with target groups for traffic distribution and health checks
5. **ASG Module**: Auto Scaling Group with Launch Template that:
   - Uses Amazon Linux 2023 AMIs
   - Runs user_data script at boot to install Docker, authenticate to ECR, pull image, fetch DB credentials from Secrets Manager, and run container
   - Performs rolling Instance Refresh when `app_version` changes (zero-downtime deployments)
6. **EC2 Module**: Single-instance bastion host for SSH access

### Secret Management Pattern
- RDS module creates Secrets Manager secret with DB credentials
- IAM instance profile grants EC2 instances permission to read the secret
- `user_data.sh` script fetches credentials at boot using AWS CLI and jq
- Credentials are passed as environment variables to Docker container
- **Critical**: Secrets never stored in Terraform state

### Rolling Update Mechanism
When `app_version` variable changes:
1. Launch Template updates with new version tag
2. ASG detects Launch Template version change
3. Instance Refresh triggers automatically (configured in `terraform/aws/modules/asg/asg.tf:38-47`)
4. Rolling strategy replaces instances gradually (50% min healthy, 90s warmup)
5. No manual ASG recreation required

## CI/CD Pipeline

### Execution Environment
- **Platform**: GitHub Actions (workflows defined in `.github/workflows/`)
- **Runner**: `ubuntu-latest` - GitHub-hosted Ubuntu virtual machines
- **Runtime**: Jobs execute in ephemeral Ubuntu VMs provisioned by GitHub, not in Docker containers or self-hosted runners
- **Pre-installed tools**: Docker, Git, AWS CLI, standard Linux utilities (jq, bash, etc.)

### Unit Test Pipeline (test.yml)
- **Trigger**:
  - Pull requests that modify `apps/**/*.py` or requirements files
  - Push to `main` that modifies Python code
  - Manual trigger via `workflow_dispatch`
- **Execution**: Two parallel testing strategies

#### Job 1: pytest (Matrix Testing)
- **Python Versions**: 3.9, 3.10, 3.11 (matrix strategy)
- **Test Runner**: pytest with coverage analysis
- **Features**:
  - Code coverage reporting with pytest-cov
  - Coverage uploaded as artifacts (Python 3.11 only)
  - PR comments with coverage percentage (via py-cov-action)
  - HTML coverage reports
  - Workflow summary with coverage metrics
- **Test Suite**: 19 unit tests covering:
  - `/liveness` endpoint (HTTP 200, HTML content, timezone, version display)
  - `/readiness` endpoint (DB connectivity checks, error handling)
  - Helper functions (`read_version()`, `check_tcp_connect()`)
  - Route validation and HTTP method restrictions
  - Edge cases (missing files, invalid ports, timeouts)

#### Job 2: unittest (Standard Library)
- **Python Version**: 3.11
- **Test Runner**: Built-in unittest module (no external dependencies)
- **Purpose**: Validates tests work with Python's standard testing framework

### Build Pipeline (build-and-publish.yml)
- **Trigger**: Push to `main` (skips if commit contains `[skip ci]`)
- **Execution**: Runs on `ubuntu-latest` GitHub-hosted runner
- **Process**:
  1. Generates image tag: `YYYYMMDDHHMMSS-<7-char-sha>`
  2. Updates `apps/version.txt` with full ECR image URL
  3. Builds and pushes Docker image to ECR with computed tag + `latest`
  4. Commits updated `version.txt` back to repo using Personal Access Token

### Deploy Pipeline (terraform-deploy-dev.yml)
- **Trigger**: Successful completion of build pipeline (`workflow_run` event)
- **Execution**: Runs on `ubuntu-latest` GitHub-hosted runner
- **Environment**: Uses GitHub environment named `dev` (may have protection rules/approvals)
- **Process**:
  1. Reads image tag from `apps/version.txt`
  2. Installs Terraform 1.13.4 in the runner VM
  3. Runs `terraform apply` with `-var="app_version=<tag>"`
  4. ASG Instance Refresh automatically triggered by Launch Template change

### Validation Pipeline (terraform-validate.yml)
- **Trigger**:
  - Pull requests that modify `terraform/**` files
  - Push to `main` that modifies `terraform/**` files
  - Manual trigger via `workflow_dispatch`
- **Execution**: Runs on `ubuntu-latest` GitHub-hosted runner
- **Adaptive Tool Detection**: Automatically detects if Terragrunt is used in the project
  - Checks for `terragrunt.hcl` or `.terragrunt-version` files
  - If found: installs Terragrunt and uses `terragrunt validate`
  - If not found: uses plain `terraform validate`
- **Process**:
  1. Detects Terragrunt presence in codebase
  2. Installs appropriate tooling (Terraform 1.13.4, optionally Terragrunt 0.55.1)
  3. Initializes Terraform with `-backend=false` (validation doesn't need remote state)
  4. Validates all Terraform configurations
  5. Checks Terraform formatting with `terraform fmt -check -recursive`
- **Current Project**: Uses plain Terraform (no Terragrunt detected)

### Security Scan Pipeline - Terraform (terraform-security-scan.yml)
- **Trigger**:
  - Pull requests that modify `terraform/**` files
  - Push to `main` that modifies `terraform/**` files
  - Manual trigger via `workflow_dispatch`
- **Execution**: Runs on `ubuntu-latest` GitHub-hosted runner
- **Tool**: tfsec (Aqua Security) - static analysis security scanner for Terraform
- **Process**:
  1. Scans all Terraform code in `terraform/` directory
  2. Generates multiple report formats: JSON, JUnit XML, SARIF, console output
  3. Uploads SARIF results to GitHub Security tab (Code Scanning alerts)
  4. Uploads all reports as workflow artifacts (7-day retention)
  5. Uses `soft_fail: true` - workflow continues even if security issues found
- **Outputs**:
  - Security findings visible in GitHub Security → Code scanning
  - Downloadable reports in workflow artifacts
  - Automatic PR comments with findings (if enabled)

### SAST Pipeline - Python Application (sast.yml)
- **Trigger**:
  - Pull requests that modify `**/*.py` or `apps/**` files
  - Push to `main` that modifies Python code
  - Manual trigger via `workflow_dispatch`
- **Execution**: Two parallel jobs on `ubuntu-latest` runners
- **Tools**:
  - **Bandit 1.7.9**: Python-specific security linter for common security issues
  - **Semgrep 1.95.0**: Semantic code analysis with multiple rulesets

#### Bandit Job:
- **Scans**: All Python code (excludes tests, venv, node_modules, terraform)
- **Severity**: Medium and above
- **Confidence**: Medium and above
- **Reports**: JSON format, converted to SARIF for GitHub Security
- **Artifacts**: Retained for 14 days

#### Semgrep Job:
- **Rulesets**:
  - `p/security-audit`: General security patterns
  - `p/secrets`: Hardcoded secrets detection
  - `p/owasp-top-ten`: OWASP Top 10 vulnerabilities
  - `p/python`: Python-specific security rules
- **Reports**: JSON, SARIF, HTML (generated with sarif-tools)
- **Artifacts**: Retained for 14 days
- **Exclusions**: tests, migrations, minified JS, node_modules, venv, terraform

#### SAST Outputs:
- Security findings in GitHub Security → Code scanning (separate categories: bandit, semgrep)
- Downloadable reports in workflow artifacts (JSON, SARIF, HTML)
- Workflow summary with issue counts and sample findings
- Both jobs use `continue-on-error: true` - workflow doesn't fail on findings

### Important CI/CD Notes
- **Separate AWS credentials** with different permissions:
  - `AWS_ACCESS_KEY_ID_ECR` / `AWS_SECRET_ACCESS_KEY_ECR`: IAM user with **ECR push permissions** (write access) - used in build pipeline to upload Docker images to ECR
  - `AWS_ACCESS_KEY_ID_TERRAFORM` / `AWS_SECRET_ACCESS_KEY_TERRAFORM`: IAM user with **Terraform management permissions** (infrastructure write access) - used in deploy pipeline
- **Why separate credentials?**: Principle of least privilege - build pipeline only needs ECR write access, deploy pipeline only needs infrastructure management access
- **PUSH vs PULL in ECR**:
  - **PUSH** (upload): GitHub Actions pipeline builds image and pushes to ECR using `AWS_ACCESS_KEY_ID_ECR` credentials
  - **PULL** (download): EC2 instances pull images from ECR using IAM instance profile with `AmazonEC2ContainerRegistryReadOnly` policy (see `terraform/aws/modules/asg/iam.tf:18-21`)
- `PERSONAL_GITHUB_TOKEN` secret used to bypass branch protection rules when committing `version.txt`
- Pipeline skips execution if actor is `github-actions[bot]` to prevent infinite loops
- GitHub Actions secrets are configured at repository level (Settings → Secrets and variables → Actions)

## Application Endpoints

The Flask application (`apps/app.py`) exposes:
- **`/liveness`**: Basic health check, returns HTML page with current Belgrade time and app version
- **`/readiness`**: Database connectivity check, returns HTTP 200 if DB reachable via TCP, HTTP 503 if unreachable. Reads `DB_ENDPOINT`, `DB_USERNAME`, `DB_PASSWORD` from environment

## Module Architecture

### Custom Modules (terraform/aws/modules/)
- **vpc**: VPC, subnets, IGW, NAT gateway, route tables
- **ecr**: ECR repository with lifecycle policies
- **alb**: ALB, listener (port 80), target group (port 8080), health check path configurable
- **asg**: Launch Template with user_data, ASG with Instance Refresh, IAM role/profile for ECR and Secrets Manager access
- **ec2**: Single EC2 instance with configurable security groups and instance profile

### Registry Modules Used
- `terraform-aws-modules/security-group/aws`: Security group management
- `terraform-aws-modules/rds/aws`: RDS MySQL instance with automatic Secrets Manager secret creation

## Key Terraform Variables

**Environment-level variables** (set in `dev.tfvars`):
- `app_version`: Docker image tag (typically set by CI/CD from `apps/version.txt`)
- `ssh_key_name`: Existing AWS key pair name for EC2 SSH access
- `my_external_ip_address`: CIDR for restricting ALB and bastion access
- `vpc_cidr`: VPC CIDR block
- `project`, `environment`, `region`: Resource naming/tagging

## Working with This Codebase

### Making Infrastructure Changes
1. Modify Terraform modules or environment configuration
2. Test locally with `terraform plan -var-file=dev.tfvars`
3. Changes to ASG Launch Template will trigger automatic rolling updates on next apply

### Deploying New App Versions
**Automated (recommended)**:
- Push code to `main` branch
- CI/CD pipelines handle build, ECR push, version update, and Terraform apply

**Manual**:
1. Build and push image to ECR with custom tag
2. Update `app_version` in environment tfvars or pass via CLI: `terraform apply -var="app_version=<tag>"`
3. ASG will automatically perform rolling Instance Refresh

### Module Dependencies
When modifying modules, note the dependency chain:
- VPC → Security Groups → RDS/ALB/ASG/EC2
- ECR → ASG (needs repository URL)
- ALB → ASG (needs target group ARN)
- RDS → ASG (needs endpoint and secret ARN)

### Important Constraints
- **SSH key pairs** must be created manually in AWS before deployment
- **Remote state backend** must be bootstrapped once before environment deployments
- **IAM users for GitHub Actions** must be created outside this repository (not managed by Terraform):
  - IAM user with ECR push permissions for `AWS_ACCESS_KEY_ID_ECR` / `AWS_SECRET_ACCESS_KEY_ECR`
  - IAM user with Terraform management permissions for `AWS_ACCESS_KEY_ID_TERRAFORM` / `AWS_SECRET_ACCESS_KEY_TERRAFORM`
  - See README.md:144 - "account-level IAM users (for personal use and GitHub actions pipelines) are expected to be created and managed outside this repository"
- **What Terraform DOES create**: IAM roles and instance profiles for EC2 instances (see `terraform/aws/modules/asg/iam.tf` and `terraform/aws/modules/ec2/iam.tf`)
- **What Terraform DOES NOT create**: IAM users for human/CI access
- Security group IDs and instance profiles are passed between modules via outputs/variables
