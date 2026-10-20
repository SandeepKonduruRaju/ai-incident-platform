output "dns_name" {
  value = aws_lb.this.dns_name
}

output "url" {
  description = "Base URL of the API (http:// in demo mode, https:// with a certificate)."
  value       = "${var.certificate_arn == null ? "http" : "https"}://${aws_lb.this.dns_name}"
}

output "target_group_arn" {
  value = aws_lb_target_group.incident_service.arn
}
