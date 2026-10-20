# tflint configuration for every Terraform root and module under infra/ (CI and local).
config {
  call_module_type = "local" # also lint the infra/modules/* used by the roots
}

plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

plugin "aws" {
  enabled = true
  version = "0.49.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}
