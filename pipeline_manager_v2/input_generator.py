import numpy as np

from pathlib import Path
from typing import Any, List, Tuple
from ase.io import write
from ase.io.espresso import write_espresso_ph
from .crystal_structure import CrystalStructure


class InputGenerator:
    def __init__(self, structure: CrystalStructure, cfg: dict):
        self.structure = structure
        self.cfg = cfg
        self.prefix = self.structure.prefix

    @staticmethod
    def _generate_kpoints_grid(nk1: int, nk2: int, nk3: int) -> np.ndarray:
        grid = np.mgrid[0:nk1, 0:nk2, 0:nk3].reshape(3, -1).T
        grid = grid / np.array([nk1, nk2, nk3])
        weights = np.full((nk1 * nk2 * nk3, 1), 1.0 / (nk1 * nk2 * nk3))
        return np.hstack([grid, weights])

    def _write_fortran_namelist(self, f, k: str, v: Any):
        if isinstance(v, list):
            for i, val in enumerate(v, 1):
                f.write(f'  {k}({i}){" ":<15}= {val}\n')
        elif isinstance(v, bool):
            f.write(f'  {k:<20}= .{str(v).lower()}.\n')
        elif isinstance(v, str):
            f.write(f"  {k:<20}= '{v}'\n")
        else:
            f.write(f'  {k:<20}= {v}\n')


class QEInputGenerator(InputGenerator):
    def __init__(self, structure: CrystalStructure, cfg: dict):
        super().__init__(structure, cfg)
        self._dispatch_map = {
            'vc-relax': self.generate_pw,
            'scf': self.generate_pw,
            'nscf': self.generate_pw,
            'bands': self.generate_pw,
            'dos': self.generate_pw,
            'phonon': self.generate_phonon,
        }

    def generate(self, stage_name: str, work_dir: Path, **overrides):
        generator_func = self._dispatch_map.get(stage_name)
        if not generator_func:
            raise ValueError(f'Unknown QE stage: {stage_name!r}')
        generator_func(stage_name, work_dir, **overrides)

    def generate_pw(self, stage_name: str, work_dir: Path, **overrides):
        mode_cfg = {**self.cfg.get(stage_name, {}), **overrides}
        input_data = {**self.cfg.get('base', {}), 'calculation': stage_name}
        input_data.update({k: v for k, v in mode_cfg.items() if k not in ('kpts', 'koffset')})

        kpts = mode_cfg.get('kpts')
        koffset = mode_cfg.get('koffset')

        if stage_name == 'nscf' and kpts:
            kpts = self._generate_kpoints_grid(*kpts)
            koffset = None

        filepath = work_dir / f'{stage_name}.{self.prefix}.in'
        write(filepath, self.structure.atoms,
              input_data=input_data,
              pseudopotentials=self.structure.pseudopotentials,
              kpts=kpts,
              koffset=koffset,
              format='espresso-in')

    def generate_phonon(self, stage_name: str, work_dir: Path, **overrides):
        ph_cfg = {**self.cfg['phonon'], **overrides}
        input_data = {k: v for k, v in ph_cfg.items() if k != 'nq'}
        input_data['prefix'] = self.prefix
        input_data['outdir'] = self.cfg.get('base', {}).get('outdir', './tmp')

        if 'nq' in ph_cfg:
            input_data['nq1'], input_data['nq2'], input_data['nq3'] = ph_cfg['nq']

        filepath = work_dir / f'phonon.{self.prefix}.in'
        with open(filepath, 'w') as f:
            write_espresso_ph(f, input_data=input_data)


class W90InputGenerator(InputGenerator):
    def __init__(self, structure: CrystalStructure, cfg: dict):
        super().__init__(structure, cfg)
        self._dispatch_map = {
            'wannier90': self.generate_wannier90,
            'pw2wannier90': self.generate_pw2wannier90,
        }

    def generate(self, stage_name: str, work_dir: Path, **overrides):
        generator_func = self._dispatch_map.get(stage_name)
        if not generator_func:
            raise ValueError(f'Unknown W90 stage: {stage_name!r}')
        generator_func(stage_name, work_dir, **overrides)

    def generate_wannier90(self, stage_name: str, work_dir: Path, **overrides):
        w90_cfg = {**self.cfg['wannier90'], **overrides}
        nk1, nk2, nk3 = w90_cfg['kgrid']
        kpts = self._generate_kpoints_grid(nk1, nk2, nk3)
        atoms = self.structure.atoms

        special_keys = ('kgrid', 'auto_projections', 'projections',
                        'scdm_entanglement', 'scdm_mu', 'scdm_sigma')

        filepath = work_dir / f'{self.prefix}.win'
        with open(filepath, 'w') as f:
            for k, v in w90_cfg.items():
                if k not in special_keys:
                    self._write_fortran_namelist(f, k, v)
            f.write('\n')

            if w90_cfg.get('auto_projections', False):
                f.write('auto_projections = .true.\n\n')
            else:
                proj_dict = {}
                for atom, orb in w90_cfg.get('projections', []):
                    proj_dict.setdefault(atom, []).append(orb)
                if proj_dict:
                    f.write('begin projections\n')
                    for atom, orbs in proj_dict.items():
                        f.write(f'{atom}: {";".join(orbs)}\n')
                    f.write('end projections\n\n')

            f.write('begin unit_cell_cart\nang\n')
            for vec in atoms.cell:
                f.write(f'  {vec[0]:.10f}  {vec[1]:.10f}  {vec[2]:.10f}\n')
            f.write('end unit_cell_cart\n\n')

            scaled = atoms.get_scaled_positions()
            symbols = atoms.get_chemical_symbols()
            f.write('begin atoms_frac\n')
            for sym, pos in zip(symbols, scaled):
                f.write(f'{sym}  {pos[0]:.10f}  {pos[1]:.10f}  {pos[2]:.10f}\n')
            f.write('end atoms_frac\n\n')

            f.write(f'mp_grid = {nk1} {nk2} {nk3}\n\n')

            f.write('begin kpoints\n')
            for kpt in kpts:
                f.write(f'  {kpt[0]:.10f}  {kpt[1]:.10f}  {kpt[2]:.10f}\n')
            f.write('end kpoints\n')

    def generate_pw2wannier90(self, stage_name: str, work_dir: Path, **overrides):
        pw2wan_cfg = {**self.cfg['pw2wannier90'], **overrides}

        filepath = work_dir / f'pw2wannier90.{self.prefix}.in'
        with open(filepath, 'w') as f:
            f.write('&inputpp\n')
            f.write(f"  {'prefix':<20}= '{self.prefix}'\n")
            f.write(f"  {'outdir':<20}= '{self.cfg.get('base', {}).get('outdir', './tmp')}'\n")
            f.write(f"  {'seedname':<20}= '{self.prefix}'\n")
            for k, v in pw2wan_cfg.items():
                self._write_fortran_namelist(f, k, v)
            f.write('/\n')


class PerturboInputGenerator(InputGenerator):
    _perturbo_modules = ('setup', 'dynamics-run', 'dynamics-pp')
    _calc_mode_map = {}

    def generate(self, stage_name: str, work_dir: Path, **overrides):
        mode_cfg = {**self.cfg.get(stage_name, {}), **overrides}
        temper = mode_cfg.pop('temper', None)   # written as a separate file, not a namelist key
        namespace = 'perturbo' if stage_name in self._perturbo_modules else 'qe2pert'

        filepath = work_dir / f'{stage_name}.{self.prefix}.in'
        with open(filepath, 'w') as f:
            f.write(f'&{namespace}\n')
            f.write(f"  {'prefix':<20}= '{self.prefix}'\n")

            if namespace == 'perturbo':
                calc_mode = self._calc_mode_map.get(stage_name, stage_name)
                f.write(f"  {'calc_mode':<20}= '{calc_mode}'\n")

            for k, v in mode_cfg.items():
                self._write_fortran_namelist(f, k, v)
            f.write('/\n')

        if temper is not None:
            self.generate_temper(work_dir, temper)

    def generate_temper(self, work_dir: Path, temp_mu_pairs: List[Tuple[float, float, float]]):
        filepath = work_dir / f'{self.prefix}.temper'
        with open(filepath, 'w') as f:
            f.write(f'  {len(temp_mu_pairs)}\n')
            for row in temp_mu_pairs:
                f.write('  ' + '  '.join(map(str, row)) + '\n')
