---
name: credential-hygiene
description: Audit and choose git and API credentials by blast radius. Use when setting up a git remote, adding a token, deciding between SSH and HTTPS, hitting a "workflow scope" push rejection, reviewing what a leaked credential would expose, or making a repository public.
---

# Credential hygiene

Pick the credential with the **smallest blast radius that still does the job**, and know what
each one costs you if it leaks.

## SSH keys and tokens are different kinds of credential

| | SSH key | Personal access token |
|---|---|---|
| Used for | git transport only | REST API **and** git over HTTPS |
| Scopes | **none — full account git authority** | scoped |
| Expiry | none unless rotated | fine-grained PATs expire |
| Limited to some repos | no | yes, if configured |
| Can push `.github/workflows/**` | **yes** | only with the workflow permission |

GitHub enforces the workflow-file guard on the **HTTPS token path only**. It does not exist
over SSH. So a push rejected as

```
refusing to allow a Personal Access Token to create or update workflow
`.github/workflows/ci.yml` without `workflow` scope
```

is the guard working. **Switching to SSH to get past it defeats a control rather than
satisfying it.** The right fix is to grant the token *Workflows: Read and write*, or to have
a human land that file.

## Ranking a credential's blast radius

Ask, in order:

1. **How many repositories?** All of them, or a selected list?
2. **Does it expire?** An unexpiring credential is a permanent liability.
3. **Can it escalate?** The critical one: does it grant `admin:public_key`, `admin:org`, or
   equivalent?
4. **Where does it live?** Keyring, environment, or plaintext on disk?
5. **Can it reach CI?** Anything that can push workflows can execute code with your Actions
   secrets and exfiltrate them.

### The escalation trap

`admin:public_key` allows `POST /user/keys`. A token holding it can **register a new SSH key
on the account**, and that key keeps working after the token is revoked. Treat any credential
carrying it as equivalent to permanent full git access, and drop the scope unless something
genuinely needs it:

```bash
gh auth refresh -s repo,read:org      # re-issue without admin:public_key
```

### Unencrypted keys

A key file with no passphrase is usable by **anything running as your user** — a package
postinstall script, an editor extension, an agent. File permissions of `600` do not help
against code running as you.

```bash
ssh-keygen -y -P '' -f ~/.ssh/id_ed25519   # succeeds => no passphrase
ssh-keygen -p -f ~/.ssh/id_ed25519         # add one; ssh-agent caches it
```

## Auditing what you actually hold

Do not assume the scopes; measure them.

```bash
# classic tokens report scopes in a header
curl -sI -H "Authorization: Bearer $TOKEN" https://api.github.com/user | grep -i x-oauth-scopes

# fine-grained tokens report no scopes; probe instead, and read the expiry
curl -sI -H "Authorization: Bearer $TOKEN" https://api.github.com/user | grep -i expiration
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOKEN" \
  https://api.github.com/repos/OWNER/SOME_OTHER_PRIVATE_REPO
# 404 => scoped to selected repositories.  200 => reaches everything.
```

A 200 against a **public** repo proves nothing — any authenticated request gets that. Always
probe a private repo you did not intend to grant.

When an endpoint returns 403, GitHub names the missing permission:

```bash
curl -sI -H "Authorization: Bearer $TOKEN" .../actions/workflows | grep -i x-accepted-github
# x-accepted-github-permissions: actions=read
```

## Storing them

- Prefer a keyring or secret manager. Note that `gh auth token` prints the token to any
  process that asks, so keyring storage is not isolation.
- A `.env` file is readable by every tool that runs in that directory, **including agents**.
  Gitignoring it prevents commits, not exposure through build contexts, backups, tarballs, or
  session transcripts.
- Never print a token into a terminal, log, or transcript. Read it into a variable and use it.
- Never embed a token in a git remote URL: it persists in `.git/config`. Pass it for one
  command instead:

  ```bash
  git -c credential.helper='!f() { echo username=x-access-token; echo password=$TOKEN; }; f' push
  ```

## Before making a repository public

Visibility change is irreversible in effect — assume anything ever committed is now archived
by third parties.

```bash
git log --all --diff-filter=A --name-only --format="" | sort -u | grep -E '\.env$|\.pem$|\.p12$'
git grep -nIE '(ghp_|gho_|ghs_|github_pat_|BEGIN [A-Z ]*PRIVATE KEY|xox[baprs]-)' $(git rev-list --all)
```

A hit means **rotate the credential first**, then clean history. Deleting the file in a new
commit does not remove it from history, and the value is already compromised.

## Reporting

State, for each credential: what it reaches, whether it expires, whether it can escalate,
where it is stored, and what an attacker gains if it leaks. Rank by blast radius, not by how
easy the fix is. Recommend the least-privilege option that still works, and say plainly when
a convenient path — such as reaching for SSH — is bypassing a control rather than satisfying it.
