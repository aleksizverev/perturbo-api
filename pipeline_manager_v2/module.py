import shutil
from dataclasses import dataclass

from pathlib import Path
from typing import List


@dataclass
class Dependency:
    target_path: Path
    uses_symlink: bool


class Module:
    def __init__(self, name: str, module_dir: Path):
        self.name: str = name
        self.module_dir: Path = module_dir
        self.stage_name: str = name   # what generate()/filenames use; dir uses name
        self.dependencies: List[Dependency] = []

    def add_dependencies(self, new_dependencies: List[Dependency]):
        self.dependencies.extend(new_dependencies)

    def resolve_dependencies(self):
        for dependency in self.dependencies:

            # check if dependency file/folder exists
            if not dependency.target_path.exists():
                raise RuntimeError(
                    f"Cannot proceed. Missing dependency: {dependency.target_path}")

            # skip if already linked (e.g. a follow-up stage in the same dir)
            destination = self.module_dir / dependency.target_path.name
            if destination.exists():
                continue

            # resolve module based on the type of connection (link/copy)
            if dependency.uses_symlink:
                destination.symlink_to(dependency.target_path.resolve())
            else:
                if dependency.target_path.is_dir():
                    shutil.copytree(dependency.target_path.resolve(),
                                    destination)
                else:
                    shutil.copy2(dependency.target_path.resolve(), destination)
