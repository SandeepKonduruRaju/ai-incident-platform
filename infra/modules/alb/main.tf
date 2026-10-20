# Public Application Load Balancer -> incident-service only (the worker, Kafka and RDS are never behind it).
#
# Two modes:
#   certificate_arn = null (DEMO, no domain): plain HTTP on port 80. Traffic, including bearer tokens, is NOT
#     encrypted. Acceptable only for a short-lived demo with test data.
#   certificate_arn = <ACM certificate>: HTTPS on 443 (TLS 1.3 policy), and port 80 only redirects to HTTPS.

# Accepted (demo): drop_invalid_header_fields is set; deletion protection and access logs are off for the demo (see below).
#trivy:ignore:AVD-AWS-0053 Internet-facing on purpose: this is the public API entry point.
resource "aws_lb" "this" {
  name                       = var.name
  internal                   = false
  load_balancer_type         = "application"
  subnets                    = var.public_subnet_ids
  security_groups            = [var.security_group_id]
  drop_invalid_header_fields = true
  enable_deletion_protection = false # demo; production: true
  idle_timeout               = 60
}

resource "aws_lb_target_group" "incident_service" {
  name                 = "${var.name}-api"
  port                 = var.target_port
  protocol             = "HTTP"
  target_type          = "ip" # Fargate tasks (awsvpc)
  vpc_id               = var.vpc_id
  deregistration_delay = 30 # in-flight requests finish before a task is stopped

  health_check {
    path                = var.health_check_path
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

#trivy:ignore:AVD-AWS-0054 HTTP-only DEMO mode when no ACM certificate is configured; with a certificate this listener only redirects to HTTPS.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = var.certificate_arn == null ? "forward" : "redirect"
    target_group_arn = var.certificate_arn == null ? aws_lb_target_group.incident_service.arn : null

    dynamic "redirect" {
      for_each = var.certificate_arn == null ? [] : [1]
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }
}

resource "aws_lb_listener" "https" {
  count = var.certificate_arn == null ? 0 : 1

  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.incident_service.arn
  }
}
