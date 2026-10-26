# One ECR repository per application image. Tags are IMMUTABLE (a git SHA always means the same image), every
# push is scanned, and only the newest images are kept.

#trivy:ignore:AVD-AWS-0033 AES-256 server-side encryption instead of a customer-managed KMS key (no extra key cost for the demo).
resource "aws_ecr_repository" "this" {
  for_each = toset(var.repository_names)

  name                 = each.key
  image_tag_mutability = "IMMUTABLE"
  force_delete         = var.force_delete # demo: "terraform destroy" removes repositories that still hold images

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "this" {
  for_each = aws_ecr_repository.this

  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep only the last ${var.keep_images} images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = var.keep_images
      }
      action = { type = "expire" }
    }]
  })
}
