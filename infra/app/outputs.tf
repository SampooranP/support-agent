output "api_url" {
  description = "Set as AGENT_API_URL in the Vercel project."
  value       = "https://${local.api_host}"
}

output "cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "service_name" {
  value = aws_ecs_service.api.name
}

output "log_group" {
  value = aws_cloudwatch_log_group.api.name
}
