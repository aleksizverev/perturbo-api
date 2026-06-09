import os
import subprocess
import shutil
import shlex
import yaml
import h5py

from pathlib import Path
from typing import List, Optional, Union
from scipy.integrate import trapezoid
from ase.io import read
from pipeline_manager_v2.crystal_structure import CrystalStructure


class Simulation:
    _executables = {}
    _dependencies = {}
    _mpirun_template = '{mpirun} -n {num_cores} {bin_dir}/{executable} -i {input}'

    def __init__(self, cfg: dict, workdir: Union[str, Path], structure: 'CrystalStructure',
                 input_generator: 'InputGenerator', pipeline: List[str]):
        self.cfg = cfg
        self.workdir = Path(workdir).resolve()
        self.structure = structure
        self.input_generator = input_generator
        self.pipeline = list(pipeline)

        self.stage_dirs = {stage: self.workdir / stage for stage in self.pipeline}

        self.num_cores = 1
        self.bin_dir = None
        self.mpirun = 'mpirun'

    def _check_runnable(self, stage_name: str):
        if not self.bin_dir:
            raise RuntimeError('Binaries directory (bin_dir) is not set')
        if stage_name not in self._executables:
            raise RuntimeError(f'No executable registered for mode {stage_name!r}')

    def _resolve_symlink_target(self, src: Union[str, Path], anchor: Path) -> Path:
        src = Path(src).resolve()
        if self.workdir in src.parents or src == self.workdir:
            return Path(os.path.relpath(src, anchor))
        return src

    def _stage_dependencies(self, stage_name: str, dest: Path, **custom_params):
        spec = self._dependencies.get(stage_name)
        if not spec:
            return

        dest.mkdir(parents=True, exist_ok=True)
        fmt = {'prefix': self.structure.prefix, 'workdir': str(self.workdir), **custom_params}
        is_link = spec['type'] == 'link'

        def _copy_or_link(src_paths: List[str], is_dir=False):
            for path_str in src_paths:
                src = Path(path_str.format(**fmt))
                dst = dest / src.name
                if is_link:
                    dst.symlink_to(self._resolve_symlink_target(src, dest))
                elif is_dir:
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy(src, dst)

        _copy_or_link(spec.get('files', []), is_dir=False)
        _copy_or_link(spec.get('folders', []), is_dir=True)

    def run(self, stage_name: str, custom_dir: Optional[Path] = None, **custom_params):
        self._check_runnable(stage_name)

        rundir = Path(custom_dir) if custom_dir else self.stage_dirs[stage_name]

        rundir.mkdir(parents=True, exist_ok=True)

        self.input_generator.generate(stage_name, rundir, **custom_params)
        self._stage_dependencies(stage_name, rundir, **custom_params)

        cmd_str = self._mpirun_template.format(
            mpirun=self.mpirun,
            num_cores=self.num_cores,
            bin_dir=self.bin_dir,
            executable=self._executables[stage_name],
            input=f'{stage_name}.{self.structure.prefix}.in'
        )

        out_file = rundir / f'{stage_name}.{self.structure.prefix}.out'

        with open(out_file, 'w') as f_out:
            subprocess.run(
                shlex.split(cmd_str),
                cwd=rundir,
                stdout=f_out,
                check=True
            )

    def run_all(self, **custom_params):
        for stage in self.pipeline:
            self.run(stage, **custom_params)


class QESimulation(Simulation):
    _executables = {
        'vc-relax': 'pw.x',
        'scf': 'pw.x',
        'nscf': 'pw.x',
        'phonon': 'ph.x',
    }

    def __init__(self, cfg, workdir, structure, input_generator, pipeline):
        super().__init__(cfg, workdir, structure, input_generator, pipeline)
        self._post_run_map = {
            'vc-relax': self._update_geometry,
            'phonon': self._collect_ph,
        }

    def run(self, stage_name: str, custom_dir: Optional[Path] = None, **custom_params):
        super().run(stage_name, custom_dir=custom_dir, **custom_params)
        rundir = Path(custom_dir) if custom_dir else self.stage_dirs[stage_name]
        post = self._post_run_map.get(stage_name)
        if post:
            post(rundir)

    def _update_geometry(self, rundir: Path):
        outfile = rundir / f'vc-relax.{self.structure.prefix}.out'
        self.structure.update_geometry(read(outfile))

    def _collect_ph(self, rundir: Path):
        """Collect phonon outputs into phonon/save/ for qe2pert."""
        ph_dir = rundir
        save_dir = ph_dir / 'save'
        phsave_dst = save_dir / f'{self.structure.prefix}.phsave'
        phsave_dst.mkdir(parents=True, exist_ok=True)

        ph0_dir = ph_dir / 'tmp' / '_ph0'

        for f in (ph0_dir / f'{self.structure.prefix}.phsave').glob('*'):
            shutil.copy(f, phsave_dst)

        for f in ph_dir.glob(f'{self.structure.prefix}.dyn*'):
            shutil.copy(f, save_dir)

        shutil.copy(
            ph0_dir / f'{self.structure.prefix}.dvscf1',
            save_dir / f'{self.structure.prefix}.dvscf_q1'
        )

        i = 0
        while True:
            ph_folder = ph_dir / 'tmp' / f'_ph{i}'
            if not ph_folder.is_dir():
                break
            for q_folder in ph_folder.glob(f'{self.structure.prefix}.q_*'):
                nq = q_folder.name.rsplit('_', 1)[-1]
                shutil.copy(
                    q_folder / f'{self.structure.prefix}.dvscf1',
                    save_dir / f'{self.structure.prefix}.dvscf_q{nq}'
                )
            i += 1


class W90Simulation(Simulation):
    _executables = {
        'wannier90': 'wannier90.x',
        'pw2wannier90': 'pw2wannier90.x',
    }

    def run(self, stage_name='wannier90', custom_dir: Optional[Path] = None, **custom_params):
        if stage_name != 'wannier90':
            raise ValueError(f'W90Simulation only handles wannier90, got {stage_name!r}')

        self._check_runnable('wannier90')
        work_dir = Path(custom_dir) if custom_dir else self.stage_dirs['wannier90']

        work_dir.mkdir(parents=True, exist_ok=True)
        self.input_generator.generate('wannier90', work_dir, **custom_params)
        self._stage_dependencies('wannier90', work_dir, **custom_params)

        # 1. preprocess
        self._run_w90(work_dir, preprocess=True)

        # 2. pw2wannier90
        saved_num_cores = self.num_cores
        self.num_cores = custom_params.get('pw2wan_cores', 16)
        super().run('pw2wannier90', custom_dir=work_dir, **custom_params)
        self.num_cores = saved_num_cores

        # 3. wannierize
        self._run_w90(work_dir, preprocess=False)

    def _run_w90(self, work_dir: Path, preprocess: bool):
        flag = '-pp ' if preprocess else ''
        cmd_str = f'{self.bin_dir}/{self._executables["wannier90"]} {flag}{self.structure.prefix}'
        subprocess.run(shlex.split(cmd_str), cwd=work_dir, check=True)


class PerturboSimulation(Simulation):
    _mpirun_template = '{mpirun} -n {num_cores} {bin_dir}/{executable} -npools {num_cores} -i {input}'
    _executables = {
        'qe2pert': 'qe2pert.x',
        'setup': 'perturbo.x',
        'dynamics-run': 'perturbo.x',
        'dynamics-pp': 'perturbo.x',
    }

    def __init__(self, cfg, workdir, structure, input_generator, pipeline):
        super().__init__(cfg, workdir, structure, input_generator, pipeline)
        self.electron_data = None
        self.K_B_meV = 8.617333262145e-2

        self._macro_map = {
            'setup': self._run_setup_macro,
            'dynamics': self._run_dynamics_macro,
        }

    def run(self, stage_name: str, custom_dir: Optional[Path] = None, **custom_params):
        macro_func = self._macro_map.get(stage_name)

        if macro_func:
            return macro_func(custom_dir=custom_dir, **custom_params)
        else:
            super().run(stage_name, custom_dir=custom_dir, **custom_params)

    def _run_setup_macro(self, custom_dir: Optional[Path] = None, **custom_params):
        sd = Path(custom_dir) if custom_dir else self.stage_dirs['setup']

        if 'temp_mu_pairs' in custom_params:
            sd.mkdir(parents=True, exist_ok=True)
            self.input_generator.generate_temper(sd, custom_params.pop('temp_mu_pairs'))

        super().run('setup', custom_dir=sd, **custom_params)

        if custom_params.get('find_efermi'):
            temper_path = sd / f'{self.structure.prefix}.temper'
            self.electron_data = self._parse_temper(temper_path)

    def _run_dynamics_macro(self, custom_dir: Optional[Path] = None, **custom_params):
        electron_data = custom_params.pop('electron_data', self.electron_data)
        lattice_temp = custom_params.pop('lattice_temp', self.structure.lattice_temp)
        eph_tmp = custom_params.pop('eph_tmp', None)

        if electron_data is None: raise RuntimeError('electron_data not provided')
        if lattice_temp is None: raise RuntimeError('lattice_temp not provided')

        base_dir = self.stage_dirs['dynamics-run']
        results = {}

        results_path = self.workdir / f'{self.structure.prefix}-gresults.txt'
        with open(results_path, 'w') as f:
            for T, mu in electron_data.items():
                t_dir = base_dir / f'T_{T:.0f}'
                overrides = {
                    'boltz_init_smear': T * self.K_B_meV,
                    'boltz_init_e0': mu,
                }

                if eph_tmp is not None:
                    t_dir.mkdir(parents=True, exist_ok=True)
                    (t_dir / 'tmp').symlink_to(self._resolve_symlink_target(eph_tmp, t_dir))
                    overrides['load_scatter_eph'] = True

                self.run('dynamics-run', custom_dir=t_dir, **overrides)

                if eph_tmp is None:
                    eph_tmp = t_dir / 'tmp'

                self.run('dynamics-pp', custom_dir=t_dir)
                results[T] = self._compute_coupling(t_dir, T, lattice_temp)

                f.write(f'{lattice_temp}  {T}  {results[T]}\n')
                f.flush()

        return results

    def _read_carrier_concentration(self):
        yml_path = self.stage_dirs['setup'] / f'{self.structure.prefix}_setup.yml'
        with open(yml_path) as f:
            data = yaml.safe_load(f)
        return data['carrier density']['configuration index'][1]['concentration']

    def _parse_temper(self, filepath: Path) -> dict:
        with open(filepath) as f:
            lines = f.readlines()
        n = int(lines[0].strip())
        mus = [float(line.split()[1]) for line in lines[1:n + 1]]
        return dict(zip(self.structure.electron_temps, mus))

    def _compute_coupling(self, pp_dir: Path, electron_temp: float, phonon_temp: float) -> float:
        Ry2eV = 13.605693
        BOHR3_TO_M3 = 1.4818474e-31
        EV_TO_J = 1.60217663e-19

        popu_path = pp_dir / f'{self.structure.prefix}_popu.h5'
        epr_path = pp_dir / f'{self.structure.prefix}_epr.h5'

        with h5py.File(popu_path, 'r') as f:
            energy = f['energy_grid_ev'][:]
            popu_t2 = f['energy_distribution/popu_t9'][:]
            popu_t1 = f['energy_distribution/popu_t1'][:]
            times = f['times_fs'][:]

        with h5py.File(epr_path, 'r') as f:
            volume_bohr3 = f['basic_data/volume'][()]

        df = popu_t2 / Ry2eV - popu_t1 / Ry2eV
        dt = (times[1] - times[0]) * 1e-15
        volume_m3 = volume_bohr3 * BOHR3_TO_M3

        power_exchange = trapezoid(df / dt * energy, energy) / volume_m3
        g = -power_exchange * EV_TO_J / (electron_temp - phonon_temp)
        return float(g)
