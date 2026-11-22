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

The layer direction is pinned too (issue #251). LAYERS below is the layer
diagram as data: every module has a number, and a module may only import
modules with a strictly lower number, so a same-layer or upward import
fails here even when it closes no cycle. When this test blocks an import,
the usual fixes keep the structure: pass the dependency in (the loader's
on_library_changed callback is the precedent) or move the shared piece
down into a lower module. Edit LAYERS only when the layering itself
should change, together with the diagram in docs/ARCHITECTURE.md. A
module need not sit at its lowest possible layer, so removing an import
never fails this test.
"""

import ast
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "itgmania_library"
PACKAGE_NAME = "itgmania_library"

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

# The layer diagram in docs/ARCHITECTURE.md as data (issue #251): higher
# numbers are built from lower ones. The two package entry files,
# __init__ and __main__, are not layered and may import anything.
LAYERS = {
    "library_librarian": 5,
    "library_table": 4,
    "library_loader": 3,
    "library_stores": 3,
    "advanced_search": 3,
    "distribution_panel": 3,
    "data_paths_dialog": 3,
    "library_filter": 2,
    "course_builder": 2,
    "library_sources": 2,
    "library_dialog_query": 2,
    "library_distribution": 2,
    "library_media": 2,
    "song_page": 2,
    "library_format": 1,
    "library_search": 1,
    "row_tints": 1,
    "window_placement": 1,
    "library_constants": 0,
    "library_geometry": 0,
    "library_course": 0,
    "theme": 0,
    "library_fonts": 0,
}
ENTRY_FILES = frozenset(("__init__", "__main__"))


def _package_modules(package=PACKAGE):
    """The module names that exist as files in the package, from the
    directory itself rather than from the import graph (which also holds
    a leaf for every imported name, existing or not)."""
    return {path.stem for path in package.glob("*.py")}


def _package_imports(package=PACKAGE):
    """The intra-package import graph and the set of modules importing
    tkinter, read from the package sources with ast. A graph entry maps a
    module to the sibling modules it imports. Every import form that can
    name a sibling is read: `from itgmania_library import x`,
    `from itgmania_library.x import y`, `import itgmania_library.x` and the
    relative `from . import x` / `from .x import y`. A name imported from
    outside the package (a typo) becomes a leaf with no imports of its
    own, so the cycle check never crashes on it — the module itself
    fails loudly elsewhere, since it cannot be imported."""
    graph = {}
    tk_modules = set()
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "tkinter" or alias.name.startswith("tkinter."):
                        tk_modules.add(path.stem)
                    elif alias.name.startswith(PACKAGE_NAME + "."):
                        imports.add(alias.name.split(".")[1])
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level == 1:
                    # `from . import x` names siblings; `from .x import y`
                    # names the sibling x. Deeper levels leave the package.
                    if module:
                        imports.add(module.split(".")[0])
                    else:
                        imports.update(alias.name for alias in node.names)
                elif node.level:
                    continue
                elif module == "tkinter" or module.startswith("tkinter."):
                    tk_modules.add(path.stem)
                elif module == PACKAGE_NAME:
                    imports.update(alias.name for alias in node.names)
                elif module.startswith(PACKAGE_NAME + "."):
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

    def test_every_module_has_a_layer_and_every_layer_has_a_module(self):
        modules = _package_modules() - ENTRY_FILES
        self.assertEqual(
            modules - set(LAYERS), set(),
            "module(s) with no layer: add them to LAYERS and to the diagram"
            " in docs/ARCHITECTURE.md")
        self.assertEqual(
            set(LAYERS) - modules, set(),
            "LAYERS names module(s) that no longer exist")

    def test_every_import_goes_to_a_strictly_lower_layer(self):
        graph, _ = _package_imports()
        offending = sorted(
            f"{module} (layer {LAYERS[module]}) imports {name}"
            f" (layer {LAYERS[name]})"
            for module in LAYERS
            for name in graph.get(module, ())
            if name in LAYERS and LAYERS[name] >= LAYERS[module])
        self.assertEqual(
            offending, [],
            "imports must go to a strictly lower layer; pass the dependency"
            " in, or move the shared piece down")


class ImportWalkTests(unittest.TestCase):
    """The walk must see every import form that can name a sibling, or the
    direction test cannot catch a violation written in that form."""

    def _graph(self, source):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            (package / "probe.py").write_text(source, encoding="utf-8")
            (package / "other.py").write_text("", encoding="utf-8")
            graph, _ = _package_imports(package)
            return graph["probe"]

    def test_from_package_import_name(self):
        self.assertEqual(
            self._graph("from itgmania_library import other\n"), {"other"})

    def test_from_package_module_import_name(self):
        self.assertEqual(
            self._graph("from itgmania_library.other import thing\n"), {"other"})

    def test_plain_import_of_a_submodule(self):
        self.assertEqual(
            self._graph("import itgmania_library.other\n"), {"other"})

    def test_relative_import_of_a_sibling(self):
        self.assertEqual(self._graph("from . import other\n"), {"other"})

    def test_relative_import_from_a_sibling(self):
        self.assertEqual(
            self._graph("from .other import thing\n"), {"other"})

    def test_a_function_level_import_is_seen(self):
        self.assertEqual(
            self._graph("def f():\n    import itgmania_library.other\n"),
            {"other"})

    def test_modules_come_from_files_not_from_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            (package / "probe.py").write_text(
                "from itgmania_library import ghost\n", encoding="utf-8")
            graph, _ = _package_imports(package)
            self.assertIn("ghost", graph)
            self.assertEqual(_package_modules(package), {"probe"})
