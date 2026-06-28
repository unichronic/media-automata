# WhatsApp Command Cheatsheet

Send `/help` on WhatsApp for the short version.

## Typical flow

1. `/todo add Product launch` — track what you need to post
2. `/post ...` — queue automated publishing
3. `/status job_<id>` — watch job progress
4. `/todo check todo_<id> linkedin` — mark platforms done on your checklist
5. `/retry job_<id>` — re-run failures if needed

---

## `/post` — publish

```text
/post this on all 3 platforms
Instagram caption - launch post
Twitter - launch post
LinkedIn - launch post
```

```text
/post to linkedin and x tomorrow 9:30am
Launch announcement copy here
```

- Attach media or quote a photo with the command as the caption.
- Bot replies with `job_<id>` — use that for `/status` and `/retry`.

---

## `/status` — job progress

```text
/status job_abc123def456
/status abc123
```

---

## `/retry` — failed tasks

```text
/retry job_abc123def456
/retry job_abc123 linkedin
/retry abc123 x
```

Platforms: `linkedin`, `x` (or `twitter`), `instagram`

---

## `/todo` — manual checklist

```text
/todo add Product launch
/todo add Product launch linkedin x
/todo list
/todo list completed
/todo list all
/todo check todo_abc123 linkedin
```

Defaults to all 3 platforms when none are listed.

---

## `/accounts` — profile health

```text
/accounts
/accounts main_brand
```

---

## Quick reference

| Command | Purpose |
|---------|---------|
| `/help` | Command list |
| `/post` | Queue publish job |
| `/status` | Job progress |
| `/retry` | Retry failed tasks |
| `/todo` | Manual post checklist |
| `/accounts` | Browser profile health |

Job and todo IDs accept a unique prefix (e.g. `abc123` instead of the full hex id).
