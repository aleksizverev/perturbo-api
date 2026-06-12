from ase import Atoms
from ase.io import read


class CrystalStructure:
    def __init__(self, atoms: Atoms, prefix: str, pseudopotentials: dict):
        self.atoms = atoms
        self.prefix = prefix
        self.pseudopotentials = pseudopotentials
        self.lattice_temp = None
        self.electron_temps = None
        self.efermi = None

    def update_geometry(self, new_atoms: Atoms):
        self.atoms = new_atoms

    def load_relaxed(self, filepath):
        self.update_geometry(read(filepath))
