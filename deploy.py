"""Deploy the already uploaded Pages artifact by ID through GitHub's REST API."""

import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def api(path, body=None):
    request = Request(
        f'https://api.github.com/repos/{os.environ["GITHUB_REPOSITORY"]}/{path}',
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f'Bearer {os.environ["GH_TOKEN"]}',
                 "Accept": "application/vnd.github+json", "Content-Type": "application/json",
                 "X-GitHub-Api-Version": "2022-11-28"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def deploy():
    artifact_id = int(os.environ["PAGES_ARTIFACT_ID"])
    request = Request(os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"], headers={
        "Authorization": f'Bearer {os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]}'})
    with urlopen(request, timeout=30) as response:
        oidc_token = json.load(response)["value"]
    deployment = api("pages/deployments", {"artifact_id": artifact_id,
                     "pages_build_version": os.environ["GITHUB_SHA"], "oidc_token": oidc_token})
    deployment_id = deployment.get("id") or deployment["status_url"].rsplit("/", 1)[-1]
    print(f"Created Pages deployment {deployment_id}", flush=True)
    failures = {"deployment_failed", "deployment_perms_error", "deployment_content_failed",
                "deployment_cancelled", "deployment_lost"}
    deadline = time.monotonic() + 600
    errors = 0
    while time.monotonic() < deadline:
        time.sleep(5)
        try:
            status = api(f"pages/deployments/{deployment_id}")["status"]
        except HTTPError as error:
            errors += 1
            if errors < 10 and (error.code == 404 or error.code >= 500):
                continue
            raise
        print(f"Pages status: {status}", flush=True)
        if status == "succeed":
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
                output.write(f'page_url={deployment["page_url"]}\n')
            return
        if status in failures:
            raise RuntimeError(f"Pages deployment failed: {status}")
    raise TimeoutError("Pages deployment did not finish in ten minutes")


if __name__ == "__main__":
    deploy()
