output "ecr_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "secret_name" {
  value = aws_secretsmanager_secret.api.name
}

output "github_deploy_role_arn" {
  description = "Set as the AWS_DEPLOY_ROLE_ARN repository variable in GitHub."
  value       = aws_iam_role.github_deploy.arn
}
