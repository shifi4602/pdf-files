from pathlib import Path
from infrastructure.pdf_reader import PdfReader
from parsers.parser_type_a import TypeAParser
from parsers.parser_type_b import TypeBParser

reader = PdfReader()
parser_a = TypeAParser()
parser_b = TypeBParser()

print("=== a_r_9 all parsed dates ===")
text9 = reader.read_text(Path("samples/a_r_9.pdf"))
report9 = parser_a.parse(text9, Path("samples/a_r_9.pdf"))
for d in report9.days:
    print(f"  {d.date} {d.date.strftime('%a')} | loc={d.location!r} | shift={'YES' if d.shift else 'NO'}")

print()
print("=== n_r_10_n all rows ===")
text10 = reader.read_text(Path("samples/n_r_10_n.pdf"))
report10 = parser_b.parse(text10, Path("samples/n_r_10_n.pdf"))
for d in report10.days:
    wd = d.date.strftime("%a")
    s = f"entry={d.shift.entry} exit={d.shift.exit}" if d.shift else "NO SHIFT"
    print(f"  {d.date} {wd} {d.day_type.value} | {s}")
print("n_r_10_n hourly_rate:", report10.summary.hourly_rate)

print()
print("=== n_r_5_n all rows ===")
text5 = reader.read_text(Path("samples/n_r_5_n.pdf"))
report5 = parser_b.parse(text5, Path("samples/n_r_5_n.pdf"))
for d in report5.days:
    wd = d.date.strftime("%a")
    s = f"entry={d.shift.entry} exit={d.shift.exit}" if d.shift else "NO SHIFT"
    print(f"  {d.date} {wd} {d.day_type.value} | {s}")
print("n_r_5_n hourly_rate:", report5.summary.hourly_rate)
