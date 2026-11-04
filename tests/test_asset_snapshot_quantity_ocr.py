import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

import numpy as np

from tasks.AssetSnapshot.quantity_ocr import InventoryQuantityOcr
from tasks.AssetSnapshot.script_task import ScriptTask


class InventoryQuantityOcrTest(unittest.TestCase):
    def test_keeps_white_grayscale_and_removes_colored_artwork(self):
        rule = InventoryQuantityOcr(roi=(0, 0, 1, 1), area=(0, 0, 1, 1),
                                    mode="Quantity", method="Default", keyword="", name="test")
        white = np.full((4, 4, 3), 190, dtype=np.uint8)
        colored = np.full((4, 4, 3), (230, 160, 40), dtype=np.uint8)
        np.testing.assert_array_equal(rule.pre_process(white), np.full((12, 12, 3), 190, dtype=np.uint8))
        self.assertFalse(rule.pre_process(colored).any())

    def test_myriad_exception_preserves_original_pixels(self):
        rule = InventoryQuantityOcr(roi=(0, 0, 1, 1), area=(0, 0, 1, 1),
                                    mode="Quantity", method="Default", keyword="", name="test")
        rule.filter_white = False
        image = np.full((23, 27, 3), (210, 180, 120), dtype=np.uint8)
        np.testing.assert_array_equal(rule.pre_process(image), image)

    def test_material_pipeline_filters_only_the_quantity_crop(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        image[294:325, 311:366] = 190
        task = ScriptTask.__new__(ScriptTask)
        task.device = SimpleNamespace(image=image)
        model = Mock()
        model.detect_and_ocr.return_value = [SimpleNamespace(ocr_text="30万", score=.99)]
        with patch("module.ocr.base_ocr.get_ocr_model", return_value=model):
            self.assertEqual(task._read_material_quantity((271, 230, 95, 70)), 300000)
        processed = model.detect_and_ocr.call_args.args[0]
        self.assertEqual(processed.shape, (192, 192, 3))
        self.assertTrue((processed[:93, :165] == 190).all())
        self.assertFalse(image[0, 0].any())


if __name__ == "__main__":
    unittest.main()
