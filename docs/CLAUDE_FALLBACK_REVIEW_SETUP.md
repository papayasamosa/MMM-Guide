# Claude fallback PR review setup

## What this does

Codex stays your normal/primary GitHub PR reviewer.

Claude does **not** review every PR or every commit.

Claude runs only when the official Codex GitHub bot posts this quota message on a PR:

`You have reached your Codex usage limits for code reviews`

The workflow then reviews the exact current PR head and posts a Claude fallback review.

## Files to add

Add these two files to the repository:

```text
.github/
├─ workflows/
│  └─ claude-fallback-review.yml
└─ claude/
   └─ fallback-review-prompt.md
```

The downloadable `.yml` and `.md` files supplied with these instructions correspond to those paths.

## Very important: merge the workflow to `main`

This workflow uses GitHub's `issue_comment` event.

For `issue_comment`, GitHub evaluates the workflow from the repository's default branch.

So install it like this:

1. Create a small branch from `main`.
2. Add only the two files above.
3. Open a small PR, for example:
   `chore: add Claude fallback PR review`
4. Merge that small PR into `main`.
5. From then on, genuine Codex quota comments can trigger Claude automatically.

Do not rely on adding the workflow only inside a feature PR that has not yet reached `main`.

## One-time Claude authentication

Anthropic's official Claude Code GitHub Action supports either:

- a Claude Code OAuth token, or
- an Anthropic API key.

### Recommended if you already use Claude Code Pro / Max

On your local machine run:

```bash
claude setup-token
```

Copy the token.

In GitHub:

1. Repository → **Settings**
2. **Secrets and variables** → **Actions**
3. **New repository secret**
4. Name:

```text
CLAUDE_CODE_OAUTH_TOKEN
```

5. Paste the token and save.

The supplied workflow already references that secret.

### Alternative: Anthropic API pay-as-you-go

Create the repository secret:

```text
ANTHROPIC_API_KEY
```

Then change this workflow line:

```yaml
claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
```

to:

```yaml
anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
```

Use one auth method, not both.

## Install the official Claude GitHub App

Anthropic's recommended setup is via Claude Code:

```text
/install-github-app
```

You can also install the official Claude GitHub App manually.

Repository-admin permission is needed for initial setup.

## Keep Codex as-is

Do not create a separate generic Claude workflow such as:

```yaml
on:
  pull_request:
```

for automatic Claude review.

Your routing remains:

```text
new PR/head
    |
    v
Codex primary review
    |
    +---- success ----------------> stop
    |
    +---- Codex quota message
               |
               v
          Claude fallback
               |
               v
        exact-head review
```

So both reviewers are not consuming allowance on every change.

## Duplicate protection

Claude's successful review comment includes:

```html
<!-- claude-fallback-review:<FULL_HEAD_SHA> -->
```

Before spending Claude usage, the workflow searches PR comments for that exact marker.

Same SHA = no duplicate Claude review.
New SHA = eligible for one fallback review if Codex is still out of quota.

## Stale-head protection

The workflow:

1. records the PR head SHA,
2. checks out that exact PR head,
3. verifies it,
4. reviews it,
5. checks GitHub again before posting.

If a commit is pushed during review, the stale review is not presented as current.

## Optional on/off switch

The fallback is enabled by default.

To disable it temporarily:

Repository → **Settings** → **Secrets and variables** → **Actions** → **Variables**

Create:

```text
CLAUDE_FALLBACK_REVIEW_ENABLED
```

with value:

```text
false
```

Delete it or change it to `true` to enable again.

## Security choices already built in

The workflow:

- accepts the quota trigger only from `chatgpt-codex-connector[bot]`
- sets Claude `allowed_bots` to that exact bot
- does not use `allowed_bots: "*"`
- loads the review prompt from the repository's default branch via the
  GitHub Contents API, before the PR head is ever checked out - a PR cannot
  rewrite its own review instructions by editing
  `.github/claude/fallback-review-prompt.md` in its own diff
- grants repository contents read-only access, and requests only the
  additional scopes actually used (`pull-requests: read` to resolve the PR
  head/base SHAs, `issues: write` to post the review comment, `actions: read`
  to let Claude inspect CI) - no `id-token` permission is requested, since
  authentication uses a static secret, not OIDC
- disables Edit and Write tools
- does not enable arbitrary Bash for Claude
- tells Claude not to commit/push/merge
- uses structured output and posts the final review itself
- does not expose full Claude output in Actions logs
- checks exact SHA before and after review
- pins `actions/checkout` and `anthropics/claude-code-action` to full commit
  SHAs (with a trailing `# vX.Y.Z` comment for readability) rather than
  mutable version tags
- is covered by a static invariant test,
  `ancestry_mmm/tests/test_claude_fallback_review_workflow.py`, that runs in
  the normal test suite and fails if any of the above regresses

## First test

After the small setup PR is merged to `main`:

1. Open GitHub → **Actions**.
2. Confirm `Claude fallback PR review` appears.
3. Confirm the Claude secret exists.
4. Confirm the Claude GitHub App has repository access.
5. Wait for a genuine Codex quota comment on a PR.

Typing the quota text yourself will not trigger Claude because the workflow verifies the comment author is the official Codex bot.

For an immediate review before that setup PR is merged, use a fresh Claude Code session manually. The workflow is primarily for future automatic fallback.
