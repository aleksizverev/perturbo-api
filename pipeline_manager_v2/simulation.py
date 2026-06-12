from pathlib import Path
from typing import List, Optional

from .crystal_structure import CrystalStructure
from .module import Module, Dependency


class Simulation:
    def __init__(self, crystal_structure: CrystalStructure, sim_dir: Path):
        self.crystal_structure: CrystalStructure = crystal_structure
        self.sim_dir: Path = sim_dir
        self.modules: dict[str, Module] = {}

    def add_module(self, name: str,
                   dependencies: Optional[List[Dependency]] = None,
                   stage: Optional[str] = None) -> Module:
        module = Module(name, self.sim_dir / name)
        module.stage_name = stage or name
        if dependencies:
            module.add_dependencies(dependencies)
        self.modules[name] = module
        return module

    def run(self, module_name: str, runner, stage=None, needs_dir=True, **overrides):
        module = self.modules.get(module_name)
        if module is None:
            raise RuntimeError(f"Module {module_name} is not registered.")

        if needs_dir:
            module.module_dir.mkdir(parents=True, exist_ok=False)
        module.resolve_dependencies()
        runner.execute(module, self.crystal_structure, stage=stage, **overrides)
