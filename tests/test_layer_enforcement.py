"""The import-graph guard (issue #189, Claude's suggestion from PR #188).

The app's modules are arranged in layers (constants at the bottom, the
window at the top), and the layer diagram in docs/ARCHITECTURE.md says
which direction imports may flow. Nothing checked that until this test:
it reads the import graph from the package with ast and fails if a cycle
appears or a module that should never touch Tkinter starts importing it.

The Tkinter boundary is pinned as an exact set: the eight modules that
import Tkinter today are the window code, plus the loader (which shows
the loading window). A ninth module gaining a tkinter import fails here
first, and a window module losing one fails the same way, so the set is
updated deliberately in either direction, with the layer diagram.
"""

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "itgmania_library"

# The modules that may import Tkinter: the window code, and the loader
# (which shows the loading window). Every other module is Tk-free.
TK_MODULES = frozenset((
    "advanced_search",
    "course_builder",
    "data_paths_dialog",
    "distribution_panel",
    "library_loader",
    "library_table",
    "library_librarian",
    "song_page",
))


def _package_imports():
    """The intra-package import graph and the set of modules importing
    tkinter, read from the package sources with ast. A graph entry maps a
    module to the sibling modules it imports. A name imported from
    outside the package (a typo) becomes a leaf with no imports of its
    own, so the cycle check never crashes on it — the module itself
    fails loudly elsewhere, since it cannot be imported."""
    graph = {}
    tk_modules = set()
    for path in sorted(PACKAGE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "tkinter" or alias.name.startswith("tkinter."):
                        tk_modules.add(path.stem)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "tkinter" or module.startswith("tkinter."):
                    tk_modules.add(path.stem)
                elif module == "itgmania_library":
                    imports.update(alias.name for alias in node.names)
                elif module.startswith("itgmania_library."):
                    imports.add(module.split(".")[1])
        graph[path.stem] = imports
    for imports in list(graph.values()):
        for name in imports:
            graph.setdefault(name, set())
    return graph, tk_modules


def _find_cycle(graph):
    """One import cycle as a list of module names, or None if the graph
    is acyclic. Depth-first, tracking the visiting stack."""
    state = {}

    def visit(module, stack):
        state[module] = "visiting"
        stack.append(module)
        for neighbour in sorted(graph[module]):
            if state.get(neighbour) == "visiting":
                return stack[stack.index(neighbour):] + [neighbour]
            if neighbour not in state:
                found = visit(neighbour, stack)
                if found is not None:
                    return found
        stack.pop()
        state[module] = "done"
        return None

    for module in sorted(graph):
        if module not in state:
            found = visit(module, [])
            if found is not None:
                return found
    return None


class LayerEnforcementTests(unittest.TestCase):
    def test_import_graph_has_no_cycles(self):
        graph, _ = _package_imports()
        self.assertIsNone(_find_cycle(graph))

    def test_tkinter_importers_are_exactly_the_window_modules(self):
        _, tk_modules = _package_imports()
        self.assertEqual(tk_modules, TK_MODULES)
