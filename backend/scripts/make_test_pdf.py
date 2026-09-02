"""Create a small test textbook PDF with chapters for end-to-end testing."""
import sys
from pathlib import Path

# ensure backend package importable when run from anywhere
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fitz  # PyMuPDF

OUT = Path(__file__).resolve().parent.parent.parent / "data" / "uploads" / "test_textbook.pdf"
OUT.parent.mkdir(parents=True, exist_ok=True)

doc = fitz.open()

def add_page(title, body):
    page = doc.new_page()
    page.insert_text((72, 80), title, fontsize=22, fontname="hebo")
    y = 130
    for para in body.split("\n"):
        page.insert_text((72, y), para, fontsize=11, fontname="helv")
        y += 18

# Chapter 3
add_page("Chapter 3: Force and Pressure", """Force is a push or a pull upon an object resulting from its interaction with another object.
Forces can cause objects to speed up, slow down, or change direction.
Pressure is defined as force per unit area. P = F / A.
Pressure increases when the same force acts on a smaller area.
That is why sharp knives cut better - smaller edge area means larger pressure.
Liquids and gases also exert pressure on the walls of their containers.""")

# Chapter 4
add_page("Chapter 4: Electricity", """Electric current is the rate of flow of electric charge through a conductor.
Current is measured in amperes using an ammeter connected in series.
Potential difference, or voltage, is the work done to move a unit charge between two points.
Voltage is measured in volts using a voltmeter connected in parallel.
Resistance is the opposition offered by a conductor to the flow of current.
Ohm's Law states that the current through a conductor is directly proportional
to the voltage across it, provided temperature remains constant. V = I x R.
If resistance increases while voltage stays constant, the current decreases.
Materials with low resistance are good conductors, like copper and aluminium.""")

add_page("Chapter 4: Electricity (continued)", """Heating effect of current: when current passes through a conductor, it heats up.
This is used in electric irons, geysers, and bulbs with filaments.
The heating is proportional to I squared times R times time (Joule's law).
Fuses protect circuits by melting when current exceeds a safe value.""")

doc.save(str(OUT))
print("test_textbook.pdf created:", doc.page_count, "pages at", OUT)
