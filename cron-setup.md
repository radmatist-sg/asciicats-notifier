# Make the watcher fire reliably — free external scheduler (cron-job.org)

GitHub's own free scheduler is unreliable, so we use a free service,
**cron-job.org**, to poke the bot every 2 minutes. Two one-time steps:

---

## Step 1 — Create a GitHub key (fine-grained token)

This key lets the scheduler start your bot. It's locked to **only this one
repo** and can do **only one thing** (start the watcher), so it's low-risk.

1. Go to: https://github.com/settings/personal-access-tokens/new
   (make sure you're logged in as **radmatist-sg**)
2. **Token name:** `mint-watcher-cron`
3. **Expiration:** 90 days (or longer)
4. **Resource owner:** radmatist-sg
5. **Repository access:** choose **Only select repositories** →
   pick **asciicats-notifier**
6. **Permissions:** expand **Repository permissions** → find **Actions** →
   set it to **Read and write**
7. Click **Generate token** and **copy** it (starts with `github_pat_...`).
   Keep it handy for Step 2. Don't share it with anyone.

---

## Step 2 — Set up the poke on cron-job.org

1. Sign up free at https://cron-job.org and log in.
2. Click **Create cronjob**.
3. **Title:** `Mint watcher poke`
4. **URL:** paste exactly:
   ```
   https://api.github.com/repos/radmatist-sg/asciicats-notifier/actions/workflows/watch.yml/dispatches
   ```
5. **Schedule:** choose **Every 2 minutes**
   (in "Custom", set it to run every 2 minutes).
6. Open the **Advanced** section and set:
   - **Request method:** `POST`
   - **Headers** (add each as a Key / Value pair):
     | Key | Value |
     |---|---|
     | `Accept` | `application/vnd.github+json` |
     | `Authorization` | `Bearer github_pat_...` ← your token from Step 1 |
     | `X-GitHub-Api-Version` | `2022-11-28` |
     | `Content-Type` | `application/json` |
   - **Request body:**
     ```
     {"ref":"main"}
     ```
7. **Save**, then click **Run now** (or "Test run") once.

A successful poke returns **HTTP 204** (that's the "OK, started" code).

---

## Step 3 — Confirm it's working

After a few minutes, tell Zul's assistant "the cron is set up" and it will
check that runs are now appearing automatically every ~2 minutes. From then
on, your `/status`, `/test`, and — most importantly — **mint-open alerts**
will fire on time, with no laptop needed.

If a poke fails with 401/403, the token is wrong or missing the Actions
permission — redo Step 1.
