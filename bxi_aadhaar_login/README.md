# Orbix Aadhaar Login (`bxi_aadhaar_login`)

Students, teachers and parents can log in by typing their **Aadhaar number** instead of their username. They then prove it is them with either:

- their normal **password**, or
- a **6-digit code emailed** to the address on their school record.

Username and email login work exactly as before. The Aadhaar number is only used to find the account; UIDAI is never contacted.

## Where the number comes from

The number lives on the student, teacher or parent record (`aadhar_card`, module `bxi_identity_verification`).

| Who sets it | How | Status |
|---|---|---|
| School office | Backend form, or `"aadhaar_number"` on the People create/update APIs | `verified` straight away |
| Family / teacher from the app | `POST /api/v1/identity/aadhar/submit` (`subject_type` `student`, `parent` or `teacher`) | `pending` until an Identity Reviewer verifies it |

Rules:

- **Format:** the number must be 12 digits, not starting with 0 or 1, with a valid Verhoeff check digit. Spaces and dashes are accepted when typed.
- **One number, one person.** A number already held by a different person is refused (`409 aadhaar_in_use`, or a validation error in the backend). The same number may sit on two records only if they are the same person, i.e. the same login or the same contact (for example, a parent who is also a teacher).
- **Lookup and display:** numbers are looked up through a keyed hash (`bxi_aadhaar_hash`, an HMAC with the database secret). API responses only show `XXXX XXXX 1234`. The number never appears in server logs.

## Settings (per school)

Settings › Orbix Notifications › Aadhaar Login, or the admin API below:

| Setting | Default | Meaning |
|---|---|---|
| Aadhaar Login | on | Offer it in the app and on /web/login |
| Email Code | on | Allow the emailed code (needs an outgoing mail server) |
| Verified Numbers Only | on | `pending` numbers can't log in until reviewed. A `rejected` number never logs in, even with this off |
| Students / Teachers / Parents | on | Which roles may use it |

To be used, a number must also be on an active record linked to an active login.

## API

All bodies are JSON. Responses use the usual `{"data": ...}` / `{"error": {"message", "code"}}` envelope.

### `GET /api/v1/auth/aadhaar/config` (public)

```json
{"enabled": true, "otp_enabled": true, "otp_channel": "email", "otp_expires_in": 600}
```

### Aadhaar + password: `POST /api/v1/auth/login`

```json
{"login_type": "aadhaar", "login": "2345 6789 0124", "password": "…", "device_name": "Orbix app"}
```

- **Response:** same as a normal login (`token`, `user`, `auth_method: "password"`), plus `"login_identifier": "aadhaar"`.
- **Without `login_type`:** a valid Aadhaar number is still detected, unless some account literally has it as its username.

| Status | Code | When |
|---|---|---|
| 400 | `invalid_aadhaar` | Not a valid Aadhaar number |
| 401 | `invalid_credentials` | Wrong password **or** a number no account may use. The two look identical |
| 409 | `ambiguous_aadhaar` | The number leads to two different logins (old data). Use the username |

### Aadhaar + emailed code

**1. Request a code:** `POST /api/v1/auth/aadhaar/otp-request` with `{"aadhaar": "2345 6789 0124"}`

```json
{"sent": true, "channel": "email", "email_hint": "s***@e***.com", "expires_in": 600}
```

- **Where the code goes:** the email on the matching record, else the account's email. For a student with neither, a linked parent's email.
- **Same reply for unknown numbers:** a number no account may use gets a made-up (but stable) hint and no email is sent, so the route can't be used to find registered numbers.
- **Resend limit:** at most one email a minute and five an hour per account. A repeat inside that window sends nothing; the previous code stays valid.

**Testing switch: code in the response.** The system parameter `bxi_aadhaar_login.otp_in_response` controls this. You can set it under Settings › Aadhaar Login › "Show Code in API Response (Testing)", or with `"otp_in_response": true` on the admin settings API. It is **off by default**. When it is on:

- The reply also carries `"otp": "123456"`.
- It is `null` for an unknown number, and `null` within a minute of the previous code (that code is still the one to use).
- A code is created even for a record without an email address.
- Each code returned this way is logged as a warning.

Anyone who knows an Aadhaar number can then log in as that person. Use it only for testing without a mail server, and switch it off before real students, teachers and parents use the app.

**2. Log in:** `POST /api/v1/auth/aadhaar/otp-login` with `{"aadhaar": "…", "otp": "123456", "device_name": "…"}`

- **Response:** same as a normal login, with `auth_method: "otp"` and `login_identifier: "aadhaar"`.
- **Codes:** each code works once and expires after 10 minutes. After 5 wrong tries, a new code is needed.
- **Errors:** `400` with code `not_found` (no code was requested, or it was already used), `expired`, `too_many_attempts` or `invalid_code`.

### Profile

`/api/v1/auth/login` and `/api/v1/auth/me` include:

```json
"aadhaar_login": {"available": true, "last4": "0124"}
```

### Admin settings (system administrators)

- `GET /api/v1/admin/aadhaar-login/settings`
- `POST /api/v1/admin/aadhaar-login/settings` with any of:

```json
{"enabled": true, "otp_enabled": true, "requires_verified": true, "roles": ["student", "teacher", "parent"],
 "otp_in_response": false}
```

`otp_in_response` is the testing switch above. It applies to every school on the server.

### People APIs (bxi_api_support)

- **Setting the number:** `aadhaar_number` (string, or `null` to clear) on `POST /api/v1/students`, `/teachers`, `/parents` and their `/update` routes.
- **In responses:** `"aadhaar": {"number_masked", "last4", "status", "verified_at"}`.
- **Errors:** `400 invalid_aadhaar`, `409 aadhaar_in_use`.

## Website

- **`/web/login`:** the login box accepts an Aadhaar number. If the login fails, the form shows the typed number again, never the username behind it.
- **`/web/login/aadhaar-code`:** a two-step page. Enter the Aadhaar number, then the emailed code.

## Rate limits

- Per IP address and per worker:
  - Aadhaar password login: 10 a minute.
  - Code requests: 5 a minute.
  - Code checks: 10 a minute.
- **Odoo's own failed-login cooldown also applies.** Both login routes go through `res.users.authenticate` with the real username. The emailed code uses the credential type `bxi_email_otp`.

## Deploying

1. Upgrade `bxi_identity_verification`, `bxi_notification_gateway` and `bxi_api_support`, then install `bxi_aadhaar_login`.
2. The upgrade of `bxi_identity_verification` (19.0.1.3.0) does three things:
   - stores existing numbers as plain 12 digits;
   - marks office-entered numbers (status `unverified`) as `verified`;
   - logs, by record ID only, any invalid numbers and numbers shared by different people.

   Fix those records in the backend afterwards.
3. The emailed code needs an outgoing mail server and a company email address (used as the sender).
