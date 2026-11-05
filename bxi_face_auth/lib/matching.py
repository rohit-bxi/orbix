# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

"""Pure decision rules for face login (no Odoo, no OpenCV): who a face
matches, and whether a challenge sequence looks like a live person."""

# Turned frames must still look like the same person as the "center" frame
# (the same person turned ~30 degrees scores well above this; different
# people average ~0.1 with SFace). Stops "hold up the victim's photo for
# the straight frame, then turn your own head".
SAME_PERSON_MIN = 0.30
# |yaw| allowed on the "center" frame, and the minimum change from it on
# each turned frame (see engine.yaw_from_landmarks: ~0.2 is ~20 degrees).
CENTER_MAX_YAW = 0.20
TURN_MIN_DELTA = 0.18

TURN_ACTIONS = ('left', 'right')


def decide(user_scores, threshold, gap, same_person=None):
    """Decide who a face belongs to.

    `user_scores` maps user id -> best similarity of the probe to that
    user's templates. `same_person` maps user id -> ids of other accounts
    staff confirmed belong to the same human (e.g. a teacher who also has a
    parent login).

    Returns (status, user_ids):
      - ('no_match', [])   best score below threshold
      - ('ambiguous', [])  another person is within `gap` of the best
      - ('match', [uid])   exactly one account
      - ('select', [...])  several accounts of the same person matched
    """
    same_person = same_person or {}
    ranked = sorted(user_scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked or ranked[0][1] < threshold:
        return 'no_match', []
    top_uid, top_score = ranked[0]
    group = {top_uid} | set(same_person.get(top_uid, ()))
    rivals = [score for uid, score in ranked[1:] if uid not in group]
    if rivals and top_score - rivals[0] < gap:
        return 'ambiguous', []
    matches = [uid for uid, score in ranked if uid in group and score >= threshold]
    return ('match' if len(matches) == 1 else 'select'), matches


def check_liveness(yaws, consistency, live_scores=None, antispoof_threshold=None):
    """Check a head-turn challenge.

    `yaws` maps action -> yaw of that frame (must contain 'center').
    `consistency` maps each turned action -> similarity to the center frame.
    `live_scores` (optional) are passive anti-spoof scores per frame.

    Returns (ok, reason, min_live_score). The sign of a turn is not
    checked against its name - front cameras may or may not mirror the
    photo - but two turns must go opposite ways.
    """
    min_live = None
    if live_scores:
        present = [score for score in live_scores if score is not None]
        min_live = min(present) if present else None
    if min_live is not None and antispoof_threshold is not None and min_live < antispoof_threshold:
        return False, 'spoof_suspected', min_live

    center = yaws.get('center')
    if center is None:
        return False, 'missing_center', min_live
    if abs(center) > CENTER_MAX_YAW:
        return False, 'not_facing_camera', min_live

    deltas = {}
    for action in TURN_ACTIONS:
        if action in yaws:
            delta = yaws[action] - center
            if abs(delta) < TURN_MIN_DELTA:
                return False, 'head_not_turned', min_live
            deltas[action] = delta
    if len(deltas) == 2 and (deltas['left'] > 0) == (deltas['right'] > 0):
        return False, 'head_not_turned', min_live

    for action, similarity in consistency.items():
        if similarity < SAME_PERSON_MIN:
            return False, 'face_changed', min_live
    return True, None, min_live
