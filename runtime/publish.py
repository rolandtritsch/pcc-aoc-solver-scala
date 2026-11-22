#!/usr/bin/env python3
"""Build the company's runtime and publish an immutable ECR image reference."""
import argparse
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--profile", default="roland")
    parser.add_argument("--region", default="eu-west-1")
    parser.add_argument("--build-label", action="append", default=[], metavar="KEY=VALUE",
                        help="Optional image metadata, including qualification-build identity")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    labels = [item for value in args.build_label for item in ("--label", value)]
    subprocess.run(["docker", "build", "--platform", "linux/amd64", "-f", "runtime/Dockerfile",
                    "-t", "pcc-aoc-runtime:local", *labels, "."], cwd=root, check=True)
    image_id = subprocess.check_output(["docker", "image", "inspect", "pcc-aoc-runtime:local",
                                        "--format", "{{.Id}}"], text=True).strip().split(":")[1]
    tag = "image-" + image_id[:16]
    aws = ["aws", "--profile", args.profile, "--region", args.region]
    password = subprocess.check_output(aws + ["ecr", "get-login-password"])
    subprocess.run(["docker", "login", "--username", "AWS", "--password-stdin",
                    args.repository.split("/")[0]], input=password, check=True)
    target = args.repository + ":" + tag
    subprocess.run(["docker", "tag", "pcc-aoc-runtime:local", target], check=True)
    subprocess.run(["docker", "push", target], check=True)
    result = json.loads(subprocess.check_output(aws + [
        "ecr", "describe-images", "--repository-name", args.repository.split("/", 1)[1],
        "--image-ids", "imageTag=" + tag,
    ]))
    print(args.repository + "@" + result["imageDetails"][0]["imageDigest"])


if __name__ == "__main__":
    main()
