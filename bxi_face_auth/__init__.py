# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import logging
import os
import sys

# numpy's and OpenCV's bundled OpenBLAS start one thread per CPU when they
# are first imported, and every thread reserves address space: on a
# 12-core machine that is ~3 GB of virtual memory for ~110 MB of real use,
# which is over Odoo's default limit_memory_hard (2.5 GB, enforced on
# address space) and makes workers fail with MemoryError. One thread per
# worker is plenty for face login (~100 ms per photo). This has to run
# before numpy is imported anywhere in the process; nothing else in this
# deployment imports numpy, and the models below are imported after it.
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS'):
    os.environ.setdefault(_variable, '1')
if 'numpy' in sys.modules or 'cv2' in sys.modules:
    logging.getLogger(__name__).warning(
        'Face login: numpy/OpenCV were imported before bxi_face_auth, so their thread pools are not '
        'capped and each worker may reserve ~3 GB of address space (over limit_memory_hard). Set '
        'OPENBLAS_NUM_THREADS=1 and OMP_NUM_THREADS=1 in the Odoo service environment.')

from . import models  # noqa: E402
from . import controllers  # noqa: E402
