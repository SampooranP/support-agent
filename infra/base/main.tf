# The long-lived, nearly free part of the deployment: the image registry, the secret holding the API's keys,
# and the role GitHub Actions assumes to push images and redeploy. It stays up between demos, so
# infra/app can be destroyed and re-created without re-entering keys. Cost: about $0.40/month for the secret.

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = var.name, ManagedBy = "terraform", Stack = "base" }
  }
}

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  # infra/app names its cluster and service after var.name; the deploy role may only touch that service.
  service_arn = "arn:aws:ecs:${var.region}:${local.account_id}:service/${var.name}/${var.name}-api"
}

# --- Image registry ---------------------------------------------------------------------------------------

resource "aws_ecr_repository" "api" {
  name                 = "${var.name}-api"
  image_tag_mutability = "MUTABLE" # the service runs :latest; each push also gets an immutable :<git sha> tag
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 10 newest images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 10 }
      action       = { type = "expire" }
    }]
  })
}

# --- Secrets ----------------------------------------------------------------------------------------------

# One JSON secret holding every key the API needs. Terraform creates it empty; you set the values with the
# AWS CLI (infra/README.md), so they never appear in Terraform code or state.
resource "aws_secretsmanager_secret" "api" {
  name        = "${var.name}/api"
  description = "Keys for the support agent API: ${join(", ", var.secret_keys)}"
}

# --- GitHub Actions deploy role (OIDC: no long-lived AWS keys in GitHub) ----------------------------------

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_github_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

locals {
  github_oidc_arn = var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : "arn:aws:iam::${local.account_id}:oidc-provider/token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "github_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      # Only workflows running on the main branch of this repository.
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name               = "${var.name}-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_trust.json
}

data "aws_iam_policy_document" "github_deploy" {
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    sid = "EcrPush"
    actions = [
      "ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:CompleteLayerUpload", "ecr:InitiateLayerUpload",
      "ecr:PutImage", "ecr:UploadLayerPart",
    ]
    resources = [aws_ecr_repository.api.arn]
  }
  statement {
    sid       = "Redeploy"
    actions   = ["ecs:UpdateService", "ecs:DescribeServices"]
    resources = [local.service_arn]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy.json
}
