# GitHub Pages deployment maintenance

The documentation workflow builds with strict MkDocs, uploads the official
`github-pages` artifact, and deploys only after the main-branch CI gates pass.
The `github-pages` environment and `pages` concurrency group remain in use.

## Deployment transport

The pinned, released `actions/github-script@v9.0.0` supplies GitHub's authenticated
client and OIDC support to [`scripts/deploy-pages.cjs`](scripts/deploy-pages.cjs).
The helper calls the official [Pages deployment API](https://docs.github.com/en/rest/pages/pages#create-a-github-pages-deployment).
It does not install or bundle another HTTP client.

The build job passes the exact uploaded artifact ID to the deployment job.
Before creating a deployment, the helper verifies its name, expiration, run ID,
commit SHA, and repository identity through the Artifact API. It then requests
the GitHub OIDC token and submits the artifact to Pages. Success requires the
Pages deployment to reach `succeed`; creating a deployment alone is insufficient.
Polling has a ten-minute deadline. A failed, timed-out, or interrupted operation
must not publish a success output; unfinished deployments are cancelled with a
bounded request.

Both the reusable workflow and its caller grant `actions: read` for artifact
verification, `contents: read` for the checked-out helper, `pages: write`, and
`id-token: write`. Checkout is pinned to the workflow commit and does not persist
Git credentials. No personal access token or additional repository secret is used.
Keep client debug output and automatic request retries disabled: a deployment
creation must not be silently repeated, and SDK exceptions may include the OIDC
request body. The helper reports bounded, sanitized failure messages.

## Why the deployment step differs from the upstream action

As checked on 2026-10-02, the latest released `actions/deploy-pages@v5.0.1`
still bundles a dependency which imports Node's deprecated `punycode` module.
The warning is tracked in [actions/deploy-pages#413](https://github.com/actions/deploy-pages/issues/413)
and [#434](https://github.com/actions/deploy-pages/issues/434); the proposed
[dependency upgrade](https://github.com/actions/deploy-pages/pull/433) is not yet
merged. This repository uses the supported REST API through a released official
action instead of suppressing deprecations, downgrading Node, or pinning an
unreleased pull request.

When upstream publishes a corrected release, review whether its deployment
lifecycle and artifact checks cover the maintained requirements before replacing
the helper. Pin the release SHA and verify an actual main-branch deployment;
do not remove the tests merely because a release note mentions the warning.

## Verification

Run the deployment regressions locally:

```sh
node --test tests/test_deploy_pages.cjs
```

The lint job repeats them under the same official Node 24 runtime used for
deployment. Tests use a local HTTP server and isolated child processes; they do
not create real Pages deployments or need a GitHub token. Review workflow YAML,
permissions, artifact outputs, and the caller's `needs` chain alongside code.

PR deployments remain skipped; the strict documentation build and deployment
regressions still run. After merging, verify the exact commit's Pages deployment,
the published site's availability, and the raw deployment log. A green PR alone
does not prove deployment success or absence of runtime warnings.
