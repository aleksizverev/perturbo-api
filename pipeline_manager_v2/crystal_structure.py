from ase import Atoms
from ase.io import read


class CrystalStructure:
    def __init__(self, cfg: dict, prefix: str):
        self.prefix = prefix
        self.atoms = Atoms(
            symbols=cfg['symbols'],
            scaled_positions=cfg['scaled_positions'],
            cell=cfg['cell'],
            pbc=True
        )
        self.pseudopotentials = cfg['pseudopotentials']
        self.lattice_temp = None
        self.electron_temps = None

    def update_geometry(self, new_atoms: Atoms):
        self.atoms = new_atoms

    def load_relaxed(self, filepath):
        self.update_geometry(read(filepath))
