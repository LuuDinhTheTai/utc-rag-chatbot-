"""Validate or seed a freshman guide from a PDF and checked-in item data."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import db
from app.freshmen import BUCKET, ItemInput, GuideUpdate, MAX_PDF_BYTES

parser=argparse.ArgumentParser()
parser.add_argument('pdf')
parser.add_argument('--apply',action='store_true')
args=parser.parse_args()
data=json.loads((Path(__file__).resolve().parents[1]/'data/freshmen_k67.json').read_text(encoding='utf-8'))
pdf_path=Path(args.pdf)
original=pdf_path.read_bytes()
if len(original)>MAX_PDF_BYTES or not original.startswith(b'%PDF-'):
    raise ValueError('PDF must be valid and <=10 MB')
pages=len(PdfReader(pdf_path).pages)
validated=[ItemInput(**row).model_dump() for row in data['items']]
if any(row['source_page']>pages for row in validated):
    raise ValueError('Item source_page exceeds source PDF page count')
GuideUpdate(title=data['title'],admission_year=data['admission_year'])
print(json.dumps({'cohort':data['cohort'],'pages':pages,'items':len(validated)}))
if not args.apply:
    sys.exit(0)
client=db()
existing=client.table('freshman_guides').select('id').eq('cohort',data['cohort']).execute().data
created=False
path=f"freshmen/{data['cohort']}/{hashlib.sha256(original).hexdigest()}.pdf"
try:
    if existing:
        guide_id=existing[0]['id']
    else:
        client.storage.from_(BUCKET).upload(path,original,{'content-type':'application/pdf','upsert':'false'})
        created=True
        row=client.table('freshman_guides').insert({
            'cohort':data['cohort'],'admission_year':data['admission_year'],
            'title':data['title'],'storage_path':path,'is_published':True
        }).execute().data[0]
        guide_id=row['id']
    rows=[row|{'guide_id':guide_id} for row in validated]
    response=client.table('freshman_items').upsert(
        rows,on_conflict='guide_id,category,code',ignore_duplicates=True).execute()
    print(json.dumps({'inserted':len(response.data),'skipped':len(rows)-len(response.data)}))
except Exception:
    if created:
        if 'guide_id' in locals():
            client.table('freshman_guides').delete().eq('id',guide_id).execute()
        client.storage.from_(BUCKET).remove([path])
    raise
