from typing import Dict, List, Set, Optional
from utils.config_manager import ConfigurationManager
from utils.exceptions import DependencyError


class DependencyNode:
    def __init__(self, name: str):
        self.name = name
        self.dependencies: Set[str] = set()
        self.suggested: Set[str] = set()


class DependencyManager:
    def __init__(self, config_manager: ConfigurationManager):
        self.config = config_manager
        self._lib_nodes: Dict[str, DependencyNode] = {}
        self._ext_nodes: Dict[str, DependencyNode] = {}

    def register_library(self, lib_name: str) -> None:
        """Register a library and its dependencies"""
        if lib_name in self._lib_nodes:
            return

        node = DependencyNode(lib_name)
        self._lib_nodes[lib_name] = node

        # Add required dependencies
        deps = self.config.get_lib_config(lib_name, 'lib-depends') or []
        for dep in deps:
            node.dependencies.add(dep)
            self.register_library(dep)

        # Add suggested dependencies
        suggests = self.config.get_lib_config(lib_name, 'lib-suggests') or []
        for suggest in suggests:
            node.suggested.add(suggest)

    def register_extension(self, ext_name: str) -> None:
        """Register an extension and its dependencies"""
        if ext_name in self._ext_nodes:
            return

        node = DependencyNode(ext_name)
        self._ext_nodes[ext_name] = node

        # Add required dependencies
        ext_deps = self.config.get_ext_config(ext_name, 'ext-depends') or []
        lib_deps = self.config.get_ext_config(ext_name, 'lib-depends') or []

        for dep in ext_deps:
            node.dependencies.add(f"ext@{dep}")
            self.register_extension(dep)

        for dep in lib_deps:
            node.dependencies.add(dep)
            self.register_library(dep)

        # Add suggested dependencies
        ext_suggests = self.config.get_ext_config(
            ext_name, 'ext-suggests') or []
        lib_suggests = self.config.get_ext_config(
            ext_name, 'lib-suggests') or []

        for suggest in ext_suggests:
            node.suggested.add(f"ext@{suggest}")
        for suggest in lib_suggests:
            node.suggested.add(suggest)

    def resolve_dependencies(self, names: List[str], include_suggested: bool = False) -> List[str]:
        """Resolve dependencies in correct build order"""
        visited: Set[str] = set()
        sorted_deps: List[str] = []

        def visit(name: str) -> None:
            if name in visited:
                return

            visited.add(name)

            # Get the appropriate node
            if name.startswith("ext@"):
                node = self._ext_nodes.get(name[4:])
            else:
                node = self._lib_nodes.get(name)

            if node is None:
                raise DependencyError(f"Dependency {name} not found")

            # Visit all dependencies
            deps = node.dependencies.copy()
            if include_suggested:
                deps.update(node.suggested)

            for dep in deps:
                visit(dep)

            sorted_deps.append(name)

        for name in names:
            visit(name)

        return sorted_deps

    def get_all_dependencies(self, names: List[str], include_suggested: bool = False) -> Set[str]:
        """Get all dependencies including transitive ones"""
        resolved = self.resolve_dependencies(names, include_suggested)
        return set(resolved)
