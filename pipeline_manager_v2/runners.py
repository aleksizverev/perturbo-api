import subprocess
import shlex

from abc import ABC, abstractmethod


class StageRunner(ABC):
    def _run(self, command, cwd, out_file=None):
        if out_file:
            with open(out_file, "w") as f:
                subprocess.run(shlex.split(command), cwd=cwd, stdout=f, check=True)
        else:
            subprocess.run(shlex.split(command), cwd=cwd, check=True)

    @abstractmethod
    def execute(self, module, structure, stage=None, **overrides):
        ...


class QERunner(StageRunner):
    def __init__(self, generator, command):
        self.generator = generator
        self.command = command

    def execute(self, module, structure, stage=None, **overrides):
        stage = stage or module.stage_name
        self.generator.generate(stage, module.module_dir, **overrides)
        prefix = structure.prefix
        input_file = f"{stage}.{prefix}.in"
        out_file = module.module_dir / f"{stage}.{prefix}.out"
        cmd = f"{self.command} -i {input_file}"
        self._run(cmd, module.module_dir, out_file)


class PerturboRunner(StageRunner):
    def __init__(self, generator, command):
        self.generator = generator
        self.command = command

    def execute(self, module, structure, stage=None, **overrides):
        stage = stage or module.stage_name
        self.generator.generate(stage, module.module_dir, **overrides)
        prefix = structure.prefix
        input_file = f"{stage}.{prefix}.in"
        out_file = module.module_dir / f"{stage}.{prefix}.out"
        cmd = f"{self.command} -i {input_file}"
        self._run(cmd, module.module_dir, out_file)


class W90Runner(StageRunner):
    def __init__(self, generator, w90_command,
                 pw2wan_command):
        self.generator = generator
        self.w90_command = w90_command
        self.pw2wan_command = pw2wan_command

    def execute(self, module, structure, stage=None, **overrides):
        cwd = module.module_dir
        prefix = structure.prefix
        self.generator.generate("wannier90", cwd)
        self.generator.generate("pw2wannier90", cwd)

        self._run(f"{self.w90_command} -pp {prefix}", cwd)
        self._run(f"{self.pw2wan_command} -i pw2wannier90.{prefix}.in", cwd)
        self._run(f"{self.w90_command} {prefix}", cwd)
