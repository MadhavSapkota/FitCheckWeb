"""Package FitCheck's static landing page and linked policy pages."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
root = Path(__file__).resolve().parents[1]
files = ('index.html', 'privacy.html', 'terms.html')
with ZipFile(root / 'fitcheck-upload.zip', 'w', ZIP_DEFLATED, compresslevel=9) as archive:
    for name in files:
        archive.write(root / name, name)
with ZipFile(root / 'fitcheck-upload.zip') as archive:
    assert set(archive.namelist()) == set(files)
    assert archive.testzip() is None
print('Created fitcheck-upload.zip containing the landing page and both policy pages.')
