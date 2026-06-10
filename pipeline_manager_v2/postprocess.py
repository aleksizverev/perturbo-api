import shutil
from pathlib import Path
from ase.io import read

from .crystal_structure import CrystalStructure


def collect_ph(module_dir: Path, structure: CrystalStructure):
    """Collect phonon outputs into <module_dir>/save/ for qe2pert."""
    prefix = structure.prefix
    save_dir = module_dir / "save"
    phsave_dst = save_dir / f"{prefix}.phsave"
    phsave_dst.mkdir(parents=True, exist_ok=True)

    ph0_dir = module_dir / "tmp" / "_ph0"

    for f in (ph0_dir / f"{prefix}.phsave").glob("*"):
        shutil.copy(f, phsave_dst)

    for f in module_dir.glob(f"{prefix}.dyn*"):
        shutil.copy(f, save_dir)

    shutil.copy(
        ph0_dir / f"{prefix}.dvscf1",
        save_dir / f"{prefix}.dvscf_q1",
    )

    i = 0
    while True:

        ph_folder = module_dir / "tmp" / f"_ph{i}"
        if not ph_folder.is_dir():
            break
        for q_folder in ph_folder.glob(f"{prefix}.q_*"):
            nq = q_folder.name.rsplit("_", 1)[-1]
            shutil.copy(
                q_folder / f"{prefix}.dvscf1",
                save_dir / f"{prefix}.dvscf_q{nq}",
            )
        i += 1

def parse_temper(filepath: Path, structure: CrystalStructure) -> dict:
    with open(filepath) as f:
        lines = f.readlines()
    n = int(lines[0].strip())
    mus = [float(line.split()[1]) for line in lines[1:n + 1]]
    return dict(zip(structure.electron_temps, mus))

def get_fermi_level(filepath):
    atoms = read(filepath)
    return atoms.calc.get_fermi_level()
