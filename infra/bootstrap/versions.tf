terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Paso 1: se aplica con estado local (este bloque comentado).
  # Paso 2: tras crear el bucket, se descomenta y se ejecuta
  #         `terraform init -migrate-state` para que TODOS los tfstate
  #         del proyecto (incluido este) vivan en S3, como pide la rúbrica.
  # backend "s3" {
  #   bucket       = "aegisvolt-tfstate-<ACCOUNT_ID>"
  #   key          = "bootstrap/terraform.tfstate"
  #   region       = "us-east-1"
  #   use_lockfile = true
  #   encrypt      = true
  # }
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
