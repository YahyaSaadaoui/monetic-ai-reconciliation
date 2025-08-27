import os, json, zipfile, pathlib
from pathlib import Path

BASE = Path('tests')
PAIRS = [
  ('pair_ok/json', 'issuer_clearing.json', 'acquirer_clearing.json'),
  ('mismatch_amount/json', 'issuer.json', 'acquirer.json'),
  ('mismatch_currency/json', 'issuer.json', 'acquirer.json'),
  ('date_out_of_tol/json', 'issuer.json', 'acquirer.json'),
  ('duplicates/json', 'issuer.json', 'acquirer.json'),
]

def main():
  for folder, a, b in PAIRS:
    p = BASE / folder
    if not p.exists():
      print(f"Skip missing {p}")
      continue
    zipname = BASE / f"{folder.replace('/', '_')}.zip"
    zipname.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zipname, 'w', zipfile.ZIP_DEFLATED) as z:
      z.write(p / a, arcname=a)
      z.write(p / b, arcname=b)
    print('Wrote', zipname)

if __name__ == '__main__':
  main()
