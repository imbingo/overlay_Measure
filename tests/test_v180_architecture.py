from __future__ import annotations

from pathlib import Path

from overlay_measure.ui_builders import MainWindowBuilderMixin
from overlay_measure.ui_components import ImageCanvas
from overlay_measure.ui_main import MainWindow, RecipeLibraryDialog
from overlay_measure.ui_recipe_actions import MainWindowRecipeMixin
from overlay_measure.ui_recipe_views import RecipeLibraryDialog as SplitRecipeLibraryDialog
from overlay_measure.ui_state import MainWindowStateMixin
from overlay_measure.ui_workflows import MainWindowWorkflowMixin


def test_ui_main_is_a_small_backward_compatible_shell():
    source_path = Path(__file__).resolve().parents[1] / "overlay_measure" / "ui_main.py"
    assert len(source_path.read_text(encoding="utf-8").splitlines()) < 500
    assert issubclass(MainWindow, MainWindowBuilderMixin)
    assert issubclass(MainWindow, MainWindowStateMixin)
    assert issubclass(MainWindow, MainWindowWorkflowMixin)
    assert issubclass(MainWindow, MainWindowRecipeMixin)
    assert RecipeLibraryDialog is SplitRecipeLibraryDialog
    assert ImageCanvas.__module__ == "overlay_measure.ui_components"
