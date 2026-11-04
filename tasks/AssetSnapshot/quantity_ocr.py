from __future__ import annotations

import cv2
import numpy as np

from module.atom.ocr import RuleOcr


class InventoryQuantityOcr(RuleOcr):
    """Suppress colored artwork around the inventory's white quantity labels."""

    filter_white = True

    def pre_process(self, image):
        if not self.filter_white:
            return super().pre_process(image)
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        low = image.min(axis=2).astype(np.int16)
        high = image.max(axis=2).astype(np.int16)
        white = (low >= 150) & (high - low <= 55)
        filtered = np.where(white, gray, 0).astype(np.uint8)
        enlarged = cv2.resize(filtered, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        return cv2.cvtColor(enlarged, cv2.COLOR_GRAY2RGB)
