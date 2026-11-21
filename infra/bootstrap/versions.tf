terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # El bootstrap se aplicó primero con estado local (huevo y gallina: el
  # bucket aún no existía) y luego se migró aquí con
  # `terraform init -migrate-state`, para que TODOS los tfstate del
  # proyecto (incluido este) vivan en S3, como pide la rúbrica.
  backend "s3" {
    bucket       = "aegisvolt-tfstate-185658217743"
    key          = "bootstrap/terraform.tfstate"
    region       = "us-east-1"
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "AegisVolt"
      Component = "bootstrap"
      ManagedBy = "Terraform"
    }
  }
}
