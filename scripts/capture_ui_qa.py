from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QMessageBox

from overlay_measure import __version__
from overlay_measure.image_loader import load_image
from overlay_measure.models import MarkRecipe
from overlay_measure.recipe_manager import load_recipe
from overlay_measure.ui_main import MainWindow


def main() -> int:
    root = ROOT
    version_slug = f"v{__version__}"
    output = root / "artifacts" / f"{version_slug}-ui"
    output.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv)
    QMessageBox.information = lambda *args, **kwargs: QMessageBox.Ok
    QMessageBox.warning = lambda *args, **kwargs: QMessageBox.Ok
    QMessageBox.critical = lambda *args, **kwargs: QMessageBox.Ok

    window = MainWindow()
    window._set_operation_mode("Engineering", authenticated=True)
    config, params, marks = load_recipe(str(root / "sample_data" / "demo_recipe.json"))
    config.workflow_mode = "Manual"
    window.config = config
    window.params = params
    window.marks = {"Mark1": marks[0], "Mark2": MarkRecipe("Mark2")}
    window.mark_images["Mark1"] = {
        "upper": load_image(str(root / "sample_data" / "sample_upper.png")),
        "lower": load_image(str(root / "sample_data" / "sample_lower.png")),
    }
    window.mark_image_sources["Mark1"] = {"upper": "single", "lower": "single"}
    window.roi_sources["Mark1"] = {"upper": "manual", "lower": "manual"}
    window.loaded_recipe_path = str(root / "sample_data" / "demo_recipe.json")
    window._push_config_to_ui()
    window._refresh_all_widgets()
    window.show()
    app.processEvents()

    window.analyze_all_marks()
    deadline = time.monotonic() + 20.0
    while window._calculation_running and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    if window._calculation_running:
        raise RuntimeError("UI QA measurement timed out")

    for width, height in ((1120, 720), (1366, 768), (1500, 920)):
        window.resize(width, height)
        app.processEvents()
        target = output / f"{version_slug}-{width}x{height}.png"
        if not window.grab().save(str(target)):
            raise RuntimeError(f"Failed to save {target}")

    window.close()
    app.processEvents()
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
