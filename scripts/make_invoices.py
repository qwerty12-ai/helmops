"""Generate synthetic invoices into data/invoices."""
from pathlib import Path
out = Path(__file__).resolve().parent.parent / "data" / "invoices"
out.mkdir(parents=True, exist_ok=True)
std = ("INVOICE\nInvoice No: {no}\nVendor: {v}\nInvoice Date: {d}\nDue Date: {due}\nTotal: USD {amt}\nNotes: {n}\n")
rows = [
    ("INV-1001", "Acme Supplies", "2026-09-01", "2026-10-10", "1,250.00", "Office furniture"),
    ("INV-1002", "Acme Supplies", "2026-09-03", "2026-10-20", "3,400.00", "Server racks"),
    ("INV-1003", "Globex Logistics", "2026-09-02", "2026-10-05", "845.50", "Freight (already in ERP)"),
    ("INV-1006", "Globex Logistics", "2026-09-10", "2026-10-08", "560.25", "Courier"),
    ("INV-1009", "Acme Supplies", "2026-09-12", "2026-10-12", "75.00", "Stationery"),
    ("INV-1005", "Umbrella Labs", "2026-09-05", "2026-11-02", "7,800.00", "Lab equipment"),
]
for no, v, d, due, amt, n in rows:
    (out / f"{no}.txt").write_text(std.format(no=no, v=v, d=d, due=due, amt=amt, n=n))
# different label style (alias handling), $ sign and long date format
(out / "INV-1004.txt").write_text("Invoice #: INV-1004\nSupplier: Initech Software\nDate: 05 Sep 2026\n"
                                  "Payment Due: 25 Oct 2026\nAmount Due: $199.00\nDescription: SaaS licences\n")
# non-USD -> blocker
(out / "INV-1007.txt").write_text("Invoice No: INV-1007\nVendor: Hooli Cloud\nInvoice Date: 2026-09-08\n"
                                  "Due Date: 2026-10-15\nTotal: EUR 920.00\nNotes: Hosting\n")
# missing amount -> blocker
(out / "INV-1008.txt").write_text("Invoice No: INV-1008\nVendor: Initech Software\nInvoice Date: 2026-09-09\n"
                                  "Due Date: 2026-10-18\nNotes: amount smudged in scan\n")
print("wrote", len(list(out.glob('*.txt'))), "invoices")
