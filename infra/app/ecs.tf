# One Fargate task running the API image. It must stay at one task: conversation locks, rate limits and
# resume scheduling live in the process's memory.

resource "aws_ecs_cluster" "main" {
  name = var.name
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.name}-api"
  retention_in_days = 7
}

data "aws_iam_policy_document" "ecs_tasks_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Used by ECS itself to pull the image, write logs and read the secret into the container's environment.
resource "aws_iam_role" "execution" {
  name               = "${var.name}-api-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secret" {
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = data.aws_secretsmanager_secret.api.arn
    }]
  })
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution.arn
  # No task role: the API calls no AWS services.

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64" # what CI builds
  }

  container_definitions = jsonencode([{
    name         = "api"
    image        = "${data.aws_ecr_repository.api.repository_url}:${var.image_tag}"
    essential    = true
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    environment = [
      { name = "AGENT_MODEL", value = var.agent_model },
      { name = "ROUTER_MODEL", value = var.router_model },
      { name = "DAILY_SPEND_CAP_USD", value = tostring(var.daily_spend_cap_usd) },
    ]
    # Each key comes from the JSON secret infra/base created and you filled in.
    secrets = [for key in var.secret_keys : { name = key, valueFrom = "${data.aws_secretsmanager_secret.api.arn}:${key}::" }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.api.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "api"
      }
    }
  }])
}

resource "aws_ecs_service" "api" {
  name            = "${var.name}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  # Stop the old task before starting the new one, so two tasks never run at once (see the note above).
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100
  health_check_grace_period_seconds  = 60

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.https]
}
