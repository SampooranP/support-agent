# The part of the deployment that costs money while it's up (about $35/month: the load balancer, its public
# IPs, and one small Fargate task). Bring it up for a demo and destroy it afterwards; infra/base keeps the
# image, the keys and the deploy role in between.

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
    tags = { Project = var.name, ManagedBy = "terraform", Stack = "app" }
  }
}

# From infra/base, looked up by name.
data "aws_ecr_repository" "api" {
  name = "${var.name}-api"
}

data "aws_secretsmanager_secret" "api" {
  name = "${var.name}/api"
}

data "aws_route53_zone" "main" {
  name = var.domain_name
}

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  api_host = "${var.api_subdomain}.${var.domain_name}"
  azs      = slice(data.aws_availability_zones.available.names, 0, 2) # a load balancer needs two
}
