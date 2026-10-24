import ast
from pathlib import Path
import unittest


class DialogParentTest(unittest.TestCase):
    def test_all_direct_file_dialogs_have_parent(self) -> None:
        source = Path(__file__).resolve().parents[1] / "automation_hub" / "gui.py"
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        dialogs = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "filedialog"
            and node.func.attr.startswith("ask")
        ]
        self.assertGreater(len(dialogs), 0)
        for call in dialogs:
            self.assertIn("parent", {item.arg for item in call.keywords}, f"line {call.lineno}")


if __name__ == "__main__":
    unittest.main()
