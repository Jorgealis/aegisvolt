terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Un objeto de estado por workspace dentro del bucket versionado:
  #   env:/dev/aegisvolt/terraform.tfstate
  #   env:/test/aegisvolt/terraform.tfstate
  #   env:/prod/aegisvolt/terraform.tfstate
  # (workspace_key_prefix por defecto = "env:")
  backend "s3" {
    bucket       = "aegisvolt-tfstate-185658217743"
    key          = "aegisvolt/terraform.tfstate"
    region       = "us-east-1"
    use_lockfile = true # lock nativo en S3 (.tflock), sin tabla DynamoDB
    encrypt      = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = local.tags
  }
}
