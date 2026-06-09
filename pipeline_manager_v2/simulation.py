import shutil
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .crystal_structure import CrystalStructure


@dataclass
class Dependency:
    target_path: Path
    uses_symlink: bool


class Module:
    def __init__(self, name: str, module_dir: Path):
        self.name: str = name
        self.module_dir: Path = module_dir
        self.dependencies: List[Dependency] = []

    def add_dependencies(self, new_dependencies: List[Dependency]):
        self.dependencies.extend(new_dependencies)

    def resolve_dependencies(self):
        for dependency in self.dependencies:

            # check if dependency file/folder exists
            if not dependency.target_path.exists():
                raise RuntimeError(
                    f"Cannot proceed. Missing dependency: {dependency.target_path}")

            # check if dependency file already exists in current directory
            destination = self.module_dir / dependency.target_path.name
            if destination.exists():
                raise RuntimeError(
                    f"Dependency {destination.name} already exists. Remove the target for rerun.")

            # resolve module based on the type of connection (link/copy)
            if dependency.uses_symlink:
                destination.symlink_to(dependency.target_path.resolve())
            else:
                if dependency.target_path.is_dir():
                    shutil.copytree(dependency.target_path.resolve(),
                                    destination)
                else:
                    shutil.copy2(dependency.target_path.resolve(), destination)


class Simulation:
    def __init__(self, crystal_structure: CrystalStructure, sim_dir: Path):
        self.crystal_structure: CrystalStructure = crystal_structure
        self.sim_dir: Path = sim_dir
        self.input_generator = None
        self.modules: dict[str, Module] = {}

    def add_module(self, name: str,
                   dependencies: Optional[List[Dependency]] = None) -> Module:
        module = Module(name, self.sim_dir / name)
        if dependencies:
            module.add_dependencies(dependencies)
        self.modules[name] = module
        return module

    def run(self, module_name: str, command: str):
        module = self.modules.get(module_name)
        if module is None:
            raise RuntimeError(f"Module {module_name} is not registered.")

        module.module_dir.mkdir(parents=True, exist_ok=False)
        self.input_generator.generate(module_name, module.module_dir)
        module.resolve_dependencies()

        prefix = self.crystal_structure.prefix
        input_file = f"{module_name}.{prefix}.in"
        command = f"{command} -i {input_file}"
        out_file = module.module_dir / f"{module_name}.{prefix}.out"
        with open(out_file, "w") as f_out:
            subprocess.run(
                shlex.split(command),
                cwd=module.module_dir,
                stdout=f_out,
                check=True,
            )
