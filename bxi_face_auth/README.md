# Orbix Face Login (`bxi_face_auth`)

Face-recognition login for the Orbix API. A person scans their face; the server works out who
they are and whether they are a **student, teacher or parent**, and returns the same bearer token
as `/api/v1/auth/login` plus an `identity` block saying so. The UI (app, admin dashboard, kiosk
app) is built separately; this module is API only.

## How it works

- **Face only (1:N, default).** The app sends just the photos. The face is searched among everyone
  enrolled at the school, with the stricter school-wide threshold and the rule that the best match
  must clearly beat the next person. The answer says who it is and their role. A setting
  (`auto_identify_enabled`) can switch this mode off, so a hint is always required.
- **With a remembered account (1:1).** The first login on a device uses a password or OTP. The app remembers what
  the user typed (login, phone number or student registration number) and sends it as
  `login_hint` on later face logins. The face is compared only with that account (or the few
  accounts sharing that phone number).
  Optional: comparing against one account accepts a little more easily, and repeated failures
  lock only that account's face login.
- **School kiosk (1:N).** A device registered by an admin sends `X-Kiosk-Key`. Same school-wide
  search, limited to the roles allowed on that kiosk. Kiosk sessions are short (15 minutes by
  default).
- **Identify without logging in.** `POST /api/v1/face/identify` answers "who is this, and what
  role?" with no session, for a gate, front desk or kiosk screen. Only kiosks and Face Login
  Managers may call it.
- **Liveness.** Every login starts with a challenge: photograph the face straight, then turned
  left and right, in a random order, within 60 seconds. A flat photo or screen can't produce the
  head turn. The turned photos must also show the same person as the straight one. An optional
  passive anti-spoof model can be added (see Deployment).
- **Matching runs on the server.** It uses OpenCV Zoo's YuNet detector (MIT) and SFace recogniser
  (Apache-2.0), CPU only, at about 0.1 s per photo. Nothing biometric is sent back to the app.
  Match scores are never returned.
- **Enrolment.**
  - **From the app:** a person (or a parent for their child) sends 3–5 photos. The enrolment
    stays *pending* until a Face Login Manager approves it.
  - **At the school desk:** staff can enrol someone in person, and it is active immediately.
  - **Students** need a parent's consent, given in the app or recorded from a signed form.
  - **Student enrolments** expire after a year (configurable), because children's faces change.
- **Storage.**
  - **Encrypted:** embeddings and a downscaled, EXIF-free copy of each photo are encrypted with
    `bxi_face_key`.
  - **Separate from the profile picture**, which users can change themselves.
  - **Deleted on exit:** when an enrolment is rejected, revoked or expires, or when consent is
    withdrawn, its photos and embeddings are deleted.
- **Face sessions are weaker sessions.** A token from face login has `auth_method: "face"`. For
  sensitive actions it must first confirm the password or an OTP through `/api/v1/auth/step-up`.
  The confirmation lasts 10 minutes.
- **Lockout.** After 5 non-matching face attempts on an account within 15 minutes, face login for
  that account pauses for 15 minutes. Password and OTP still work, and the user gets a push
  notification. Photo problems (blur, no face) don't count. This needs a `login_hint` to know
  which account was tried; face-only and kiosk attempts are limited per IP instead (10 a minute
  per worker; add a limit at the reverse proxy too).

## Deployment

1. Install OpenCV on the server's Odoo Python. numpy comes with it.
   ```
   pip install opencv-python-headless
   ```
2. Add an encryption key to the Odoo config file. Keep it out of database backups and don't lose
   it: face data can't be decrypted without it.
   ```
   bxi_face_key = <long random string, e.g. output of: python3 -c "import secrets; print(secrets.token_urlsafe(48))">
   ```
   Without it, a key is generated and stored in the database (a warning is logged). It still
   works, but then a database dump contains the key as well.
   - **Changing the key:** set the new key as `bxi_face_key` and the old one as
     `bxi_face_key_previous` until everyone has re-enrolled.
3. Upgrade `bxi_api`, `bxi_notification_gateway` and `bxi_identity_verification`, then install
   `bxi_face_auth`:
   ```
   -u bxi_api,bxi_notification_gateway,bxi_identity_verification -i bxi_face_auth
   ```
4. Recommended: set `OPENBLAS_NUM_THREADS=1` and `OMP_NUM_THREADS=1` in the Odoo service's
   environment (e.g. `Environment=` lines in the systemd unit). The module sets them itself, but
   only takes effect if nothing imported numpy first (see Memory below).
5. Give the reviewers the **Face Login Manager** group (system admins have access anyway).
6. Turn it on: `POST /api/v1/admin/face/settings {"enabled": true}`. It is off after install.

**Optional config keys:**
- `bxi_face_model_dir`: a different model directory. The default is `ml_models/` in this module.
- `bxi_face_antispoof_model`: path to a passive anti-spoof ONNX model in the Silent-Face
  MiniFASNet convention (80×80 crop of the face box scaled ×2.7, 3-class softmax, class 1 =
  real). A `face_antispoof_minifasnet.onnx` file in the model directory is picked up
  automatically. When present, its score is checked against `antispoof_threshold`.

**Memory.** numpy and OpenCV are limited to one thread per Odoo worker (`OPENBLAS_NUM_THREADS` /
`OMP_NUM_THREADS`, set by this module unless already set in the environment). With their default
of one thread per CPU, a worker reserves about 3 GB of address space. That is over Odoo's default
`limit_memory_hard` (2.5 GB) and fails with `MemoryError`. Don't set these variables higher for
the Odoo service.

The limit only works if numpy is first imported by this module. For that reason the manifest
names the PyPI package `opencv-python-headless` rather than `cv2`: for an import name, Odoo's
install/upgrade dependency check falls back to actually importing it. `openpyxl` (spreadsheet
import/export) also imports numpy when it loads, and Odoo's own test suite loads it early. If the
log shows "numpy/OpenCV were imported before bxi_face_auth", set both variables in the service
environment. Measured on a 12-core machine: 0.35 GB per worker with both capped, 1.3 GB if only
OpenCV is capped, 2.9–3.1 GB with neither.

## For the front-end team

All responses use the usual envelope: `{"success": true, "data": …}` or
`{"success": false, "error": {"message", "code", …}}`. Photos are JPEG or PNG, base64 in JSON. A
`data:image/jpeg;base64,` prefix is accepted. Multipart file uploads also work. Use the front
camera, at least 640×480, under 5 MB per photo, with one face clearly visible. Mirrored or
unmirrored photos are both fine.

### Log in with face

1. **Get a challenge:**
   ```
   POST /api/v1/auth/face-login/challenge                       (no auth, no body)
   → {"challenge_id": "fc_…", "actions": ["center", "right", "left"], "expires_in": 60}
   ```
2. **Prompt and capture.** Show the prompts in the order given: *look straight*, *turn your head
   right*, *turn your head left*. Take one photo per action (a turn of about 20–30° is enough),
   then send them together:
   ```
   POST /api/v1/auth/face-login
   {
     "challenge_id": "fc_…",
     "device_name": "Aarav's phone",
     "login_hint": "9876543210",          // optional: what the user logged in with last time on this device
     "frames": [
       {"action": "center", "image": "<base64>"},
       {"action": "right",  "image": "<base64>"},
       {"action": "left",   "image": "<base64>"}
     ]
   }
   ```
   - **Multipart alternative:** form fields `challenge_id`, `login_hint`, `device_name`, and one
     file part per action, named `center` / `left` / `right`.
   Without `login_hint`, the server identifies the person from the face alone.
3. **Success:** the response is the same as `/auth/login`, plus `auth_method` and `identity`:
   ```
   {
     "token": "orb_…",
     "auth_method": "face",
     "user": {…roles, student_id, parent_id, faculty_id, student_ids…},
     "identity": {
       "user_id": 42,
       "name": "Aarav Shah",
       "role": "student",                       // student | teacher | parent | staff
       "roles": ["student"],                    // every role face login may use for this account
       "student": {"id": 12, "name": "Aarav Shah", "gr_no": "STU-0012",
                   "class": {"id": 3, "name": "Class 7"}, "section": {"id": 8, "name": "7-B"}},
       "teacher": null,                         // {"id", "name"} for a teacher
       "parent": null                           // {"id", "name", "children": [same shape as student]} for a parent
     }
   }
   ```
   Open the screens for `identity.role`. `role` is the first of student → teacher → parent → staff
   that this account has *and* face login is allowed for. A teacher who is also a parent on the
   same account gets `"role": "teacher"`, `"roles": ["teacher", "parent"]` and both records, so
   the app can offer a switch.
4. **One face, several accounts** (e.g. a teacher who also has a parent login, confirmed by staff):
   ```
   {"selection_required": true, "selection_token": "fs_…", "expires_in": 120,
    "accounts": [<identity of account 7, role "teacher">, <identity of account 9, role "parent">]}
   ```
   Show the choice, then:
   ```
   POST /api/v1/auth/face-login/select {"selection_token": "fs_…", "user_id": 9}
   ```
   The response is the same as step 3. No second scan is needed.

A **challenge is single-use**. After any error, start again from step 1.

### Kiosk

The same three calls, with header `X-Kiosk-Key: kiosk_…` (from `POST /api/v1/admin/face/kiosks`)
and no `login_hint`. `identity.roles` only lists roles allowed on that kiosk.

### Identify without logging in

For a gate, front desk or kiosk screen that only needs to know who someone is. The challenge and
photos are the same as for login; no token is issued.
```
POST /api/v1/face/identify                 X-Kiosk-Key: kiosk_…   or   Authorization: Bearer <Face Login Manager token>
{"challenge_id": "fc_…", "frames": [...]}
→ {"identified": true,  "reason": null, "identity": {…as above…}, "accounts": [<identity>, …]}
→ {"identified": false, "reason": "face_not_recognised" | "ambiguous", "identity": null, "accounts": []}
```
`accounts` has more than one entry only when staff confirmed one person has several accounts.
Errors are the same photo and liveness errors as login, plus 401 `unauthorized` / `invalid_kiosk`,
403 `forbidden` (not a Face Login Manager) and 403 `face_login_disabled`.

### Face login errors

| HTTP | `error.code` | Meaning | What to do |
|---|---|---|---|
| 400 | `challenge_expired` | Unknown, used or older than 60 s | New challenge |
| 400 | `invalid_frames` | Not exactly one photo per action | Fix the request |
| 400 | `missing_login_hint` | No hint, and face-only login is switched off at this school | Send the remembered hint |
| 400 | `invalid_image` | Not a readable JPEG/PNG (`error.action` / `error.frame` say which) | Retake |
| 400 | `no_face`, `multiple_faces`, `poor_quality` | Photo unusable (no face, two people, too small/blurred) | Show the message, retake |
| 401 | `liveness_failed` | Head turn missing, or a different face in the turned photos | Retry, or password/OTP |
| 401 | `face_not_recognised` | No match, not enrolled, face login off for this account, or unknown hint. This is deliberately one code | Password/OTP |
| 401 | `invalid_kiosk` | Kiosk key unknown or revoked | Re-register the kiosk |
| 403 | `face_login_disabled` | Kiosks switched off | — |
| 409 | `ambiguous` | Too close to another person | Password/OTP |
| 423 | `locked` | Too many failed attempts on this account | Password/OTP, or wait |
| 429 | `rate_limited` | Too many requests from this IP | Wait a minute |
| 503 | `face_engine_unavailable` | Server-side problem | Password/OTP |

### Step-up (sessions opened by face)

Routes that answer **403 `step_up_required`** need a fresh password or OTP confirmation:
```
POST /api/v1/auth/step-up {"password": "…"}
POST /api/v1/auth/step-up/otp-request                (texts an OTP to the account's own phone)
POST /api/v1/auth/step-up {"otp": "123456"}
→ {"verified": true, "verified_until": "2026-11-03 10:15:00"}
```
Then retry the original request within 10 minutes.

**Routes guarded for face sessions** (password/OTP sessions pass straight through):
- `POST /api/v1/identity/link-student`, `/identity/unlink-student`, `/identity/aadhar/submit`,
  `/identity/face/submit`
- `POST /api/v1/auth/sessions/<id>/revoke`
- `POST /api/v1/face/consent`, `/face/disable`

**`POST /api/v1/face/enroll`** is stricter. Every session must have confirmed within the last
10 minutes. Logging in with a password or OTP counts, so right after a normal login it just works.

### Managing your own face login (any logged-in user)

| Endpoint | Body | Notes |
|---|---|---|
| `GET /api/v1/face/status` | — | `{face_login_enabled, self: {...}, children: [...]}`. Each status has `state` (`none`/`pending`/`active`/`rejected`/`expired`), `can_use_face_login`, `unavailable_reason`, `enrolled_at`, `expires_at`, `pending_since`, `reject_reason`. Children also have `student_id`, `name`, `has_account`, `consent`. |
| `POST /api/v1/face/enroll` | `{"consent": true, "frames": [{"image": …}, …]}` (3–5 photos, at least one looking straight, optionally a couple slightly turned). Parents add `"student_id"` to enrol a child; `consent: true` then records the parent's consent. | Answers with the status (`state: "pending"`) and `enrolment_id`. Errors: `consent_required`, `no_frontal_face`, `inconsistent_faces`, `student_has_no_account`, `role_not_allowed`, `disabled`, plus the photo errors above. |
| `POST /api/v1/face/consent` | `{"student_id": 12, "granted": true\|false}` | Parent only. `false` deletes the child's face data at once. |
| `POST /api/v1/face/disable` | `{}` or `{"student_id": 12}` | Turns face login off and deletes the face data. |

A student can enrol themselves only after a parent has consented.

### Admin dashboard (Face Login Manager or system admin)

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/admin/face/enrolments?state=pending&role=student\|teacher\|parent&search=&user_id=&limit=&offset=` | Review queue (pending oldest first). Each item has the person, roles, class, who submitted it, consent, and `duplicates` (other enrolled accounts this face matched). |
| `GET /api/v1/admin/face/enrolments/<id>` | Same, plus per-photo quality (`yaw`, `detection_score`, `face_pixels`, `sharpness`). |
| `GET /api/v1/admin/face/enrolments/<id>/photos` | `photos[].image` (base64 JPEG) and `record_photo` (the photo on the school record) for side-by-side comparison. |
| `POST /api/v1/admin/face/enrolments/<id>/approve` | `{}`. If the face matches other accounts it answers **409 `duplicate_review_required`** with the list. Resend with `"same_person_user_ids": [..]` (same human, several logins: face login will offer a choice) or `"ignore_duplicates": true` (different people). Students also need consent on record (`consent_required`). |
| `POST /api/v1/admin/face/enrolments/<id>/reject` | `{"reason": "Too dark"}`. Photos are deleted; the reason is shown to the user. |
| `POST /api/v1/admin/face/enrolments/<id>/revoke` | `{"reason": "…"}`. Ends an active or pending enrolment. |
| `POST /api/v1/admin/face/enrol` | In-person enrolment: one of `user_id` / `student_id` / `faculty_id` / `parent_id`, plus `frames` (1–5). For a student without consent on record, add `"consent_reference": "Form 2026/118"`. Active at once, unless the face matches another account (then it stays `pending` with `duplicates`). |
| `GET /api/v1/admin/face/attempts?user_id=&result=&mode=phone\|auto\|kiosk\|identify&kiosk_id=&date_from=&date_to=` | Login attempt log, with scores, for auditing and tuning. |
| `GET /api/v1/admin/face/kiosks` | Kiosk list. |
| `POST /api/v1/admin/face/kiosks` | `{"name": "Library tablet", "roles": ["student", "teacher"], "session_minutes": 15}`. The response contains `key` **once**. |
| `POST /api/v1/admin/face/kiosks/<id>/revoke` | Disables the key and ends sessions opened on that kiosk. |
| `GET/POST /api/v1/admin/face/settings` | See below. GET also returns `engine` (model status), `encryption_key_source` (`config` or `database`) and enrolment counts. |

**Settings** (POST any subset):

| Setting | Default | Notes |
|---|---|---|
| `enabled` | `false` | Master switch for the school |
| `allow_student`, `allow_teacher`, `allow_parent` | `true` | Which roles may use face login |
| `allow_staff` | `false` | Non-teaching staff and **administrators** |
| `student_consent_required` | `true` | Parental consent before a student's face is processed |
| `student_class_ids` | `[]` | Limit students to these classes (empty = all) |
| `kiosk_enabled` | `true` | |
| `auto_identify_enabled` | `true` | Face-only login without `login_hint` (school-wide search) |
| `match_threshold` | `0.45` | Own phone, 0.2–0.95 |
| `kiosk_match_threshold` | `0.55` | Kiosk, 0.2–0.95 |
| `kiosk_match_gap` | `0.10` | 0–0.5 |
| `liveness_required` | `true` | Head-turn check. When off, the turned photos must still be the same person |
| `antispoof_threshold` | `0.80` | Only with an anti-spoof model |
| `max_failures`, `lockout_minutes` | `5`, `15` | |
| `student_validity_days` | `365` | 0 = never expires |
| `token_days` | `30` | Length of a face session on a phone |
| `attempt_retention_days` | `180` | |
| `consent_version` | `"1"` | Bump when the consent wording shown in the app changes |

## Other API changes that came with this module

- **`POST /api/v1/identity/link-student` now needs proof that the parent knows the child:**
  `{"gr_no": "<registration number>", "birth_date": "YYYY-MM-DD"}` (`student_id` optional).
  Before, any parent account could attach any student by id and then see that child's data.
  Errors:
  - `403 verification_failed`: the details don't match, or the student has no date of birth on
    record.
  - `400 missing_fields` / `invalid_birth_date`.
- **Identity endpoints treat only Identity Reviewers (and system admins) as staff.** Before,
  every internal user counted, and family accounts are often internal users in this deployment.
- **Every login response now includes `auth_method`** (`password`, `otp`, `face`, `face_kiosk`),
  and so does `GET /api/v1/auth/sessions`.

## Tuning and limits

- **Thresholds are starting values.** On 12 public-domain portraits, the same person scored
  0.77–0.91 and different people averaged 0.12, but the closest pair of different people scored
  0.37. That is why the defaults are stricter than SFace's published 0.363. During the pilot,
  check `best_score` / `second_score` in the attempt log and adjust.
- **Identical twins can't be told apart by face.** On kiosks they get `ambiguous`. On a phone,
  `login_hint` decides which account is tried, but a twin could open their sibling's account if
  given the hint. Turn face login off for such accounts if that matters.
- **The head-turn challenge stops photos and screens of a single picture.** It won't stop a
  replayed video of the person turning their head in the same order, or a 3D mask. If that
  matters, install a passive anti-spoof model or use a commercial liveness service. Step-up on
  sensitive actions limits what a face session can do either way.
