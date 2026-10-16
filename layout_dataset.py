"""Independent layout-ready sidecar, readiness gates and lossless source crops."""
from __future__ import annotations
import copy
import json
from pathlib import Path
from PIL import Image
from translation_evidence import digest, file_hash, incomplete

CHECKS=('pairing','translation','formulas','geometry','region_coverage','reading_order','page_template')


def load_reviews(path):
    data=json.loads(Path(path).read_text(encoding='utf8'))
    if not isinstance(data,dict) or not isinstance(data.get('reviews'),list):raise ValueError('Expected reviews list')
    for r in data['reviews']:
        if (not isinstance(r,dict) or r.get('verified') is not True
            or any(not isinstance(r.get(k),str) or not r[k].strip() for k in ('reviewer','basis'))
            or any(not isinstance(r.get(k),str) or len(r[k])!=64 or any(c not in '0123456789abcdef' for c in r[k])
                   for k in ('source_sha256','generated_sha256','evidence_sha256','regions_sha256'))
            or not isinstance(r.get('checks'),dict) or any(type(r['checks'].get(k)) is not bool for k in CHECKS)):
            raise ValueError('Independent reviews need reviewer, basis, hashes and explicit boolean checks')
    return copy.deepcopy(data['reviews'])


def assess_readiness(dataset):
    regions=dataset.get('region_qc')
    if regions and (regions.get('high_risk') or any(w.get('high_risk') or w.get('risk')=='MATH_HIGH_RISK' for w in regions.get('warnings',[]))):
        return {'status':'HIGH_RISK_HOLD','missing':['Independent adjudication of serious region/content risks'],
                'blocks_batch':False,'eligible_for_final_page':False}
    missing=[]
    if dataset['translation'].get('status')!='COLLECTED_UNVERIFIED':missing.append('Bound, completed translation response')
    if not regions or not isinstance(regions.get('regions'),dict) or any(not isinstance(regions['regions'].get(s),list) for s in ('source','generated')):
        missing.append('Source/generated region evidence')
    else:
        unresolved=[r['id'] for rs in regions['regions'].values() for r in rs if r.get('comparison_type')=='UNKNOWN'
                    or (r.get('confidence',0)<.70 and not r.get('classification_verified'))]
        if unresolved:missing.append('Unresolved or low-confidence regions: '+', '.join(unresolved))
        if regions.get('pairing',{}).get('status')=='CONFLICT':missing.append('Conflicting pairing evidence')
    if regions:
        formulas=[r for rs in regions.get('regions',{}).values() if isinstance(rs,list) for r in rs if r.get('comparison_type')=='MATH_FORMULA']
        if formulas and not any(isinstance(f,dict) and isinstance(f.get('raw'),str) and f['raw'].strip() for f in dataset['translation'].get('formulas',[])):
            missing.append('Original formula representation for known formula regions')
        geometry=[r for r in regions.get('regions',{}).get('source',[]) if r.get('comparison_type')=='GEOMETRY_DIAGRAM']
        extracted={r.get('region_id') for r in dataset.get('geometry_crops',[]) if r.get('decoded_pixels_exact') is True}
        if any(r['id'] not in extracted for r in geometry):missing.append('Exact-pixel source geometry assets')
    if dataset.get('pairing_status')!='BOUND':missing.append('Text/source/generated hash association')
    bindings={'source_sha256':dataset['source_image']['sha256'],'generated_sha256':dataset['translated_image']['sha256'],
              'evidence_sha256':dataset['evidence_sha256'],'regions_sha256':dataset['regions_sha256']}
    verified=[r for r in dataset.get('independent_reviews',[]) if r.get('verified') is True
              and all(r.get(k)==v for k,v in bindings.items()) and isinstance(r.get('reviewer'),str) and r['reviewer'].strip()
              and isinstance(r.get('basis'),str) and r['basis'].strip()]
    checks={k:any(r.get('checks',{}).get(k) is True for r in verified) for k in CHECKS}
    missing.extend('Independent verification: '+k for k in CHECKS if not checks[k])
    return {'status':'EVIDENCE_INCOMPLETE' if missing else 'READY_FOR_PILOT','missing':missing,
            'verified_checks':checks,'blocks_batch':False,'eligible_for_final_page':False,
            'scope':'Pilot readiness only; no final-page assembly or automatic math edits'}


def build_dataset(source,generated,*,evidence=None,region_qc=None,metadata=None,reviews=()):
    source,generated=Path(source).resolve(),Path(generated).resolve()
    hashes={'source':file_hash(source),'generated':file_hash(generated)}
    e=copy.deepcopy(evidence) if evidence else incomplete('No ChatGPT translation text exists in the offline inputs')
    bound=(e.get('source_sha256')==hashes['source'] and e.get('generated_sha256')==hashes['generated']
           and isinstance(e.get('capture_token'),str) and bool(e['capture_token'])
           and e.get('association')=='same_page_worker_capture_session')
    if e.get('status')=='COLLECTED_UNVERIFIED':
        import hashlib
        valid_text=(isinstance(e.get('text'),str) and bool(e['text'].strip())
                    and e.get('text_sha256')==hashlib.sha256(e['text'].encode('utf8')).hexdigest())
        payload={k:e.get(k) for k in ('text','html','blocks','formulas')}
        if not bound or not valid_text or e.get('response_sha256')!=digest(payload):
            e=incomplete('Text response hash or image binding does not match')
    d={'dataset_version':'layout-ready-v1','source_image':{'path':str(source),'sha256':hashes['source'],'status':'COLLECTED_UNVERIFIED'},
       'translated_image':{'path':str(generated),'sha256':hashes['generated'],'status':'COLLECTED_UNVERIFIED'},
       'translation':e,'region_qc':copy.deepcopy(region_qc),'metadata':dict(metadata or {}),
       'pairing_status':'BOUND' if bound and e.get('status')=='COLLECTED_UNVERIFIED' else 'EVIDENCE_INCOMPLETE',
       'evidence_sha256':digest(e),'regions_sha256':digest(region_qc),
       'independent_reviews':copy.deepcopy(list(reviews)),
       'geometry_crops':[],'verification_scope':'Collected data and heuristic classes do not certify translation or mathematics'}
    d['readiness']=assess_readiness(d)
    d['dataset_sha256']=digest(d)
    return d


def export_geometry_crops(dataset,directory):
    """Raw pixel crop only. No scaling, rotation, relabeling or insertion."""
    root=Path(directory);root.mkdir()
    source=Path(dataset['source_image']['path']);expected=dataset['source_image']['sha256']
    if file_hash(source)!=expected:raise ValueError('Source changed before extraction')
    rows=[]
    with Image.open(source) as im:
        if getattr(im,'n_frames',1)!=1 or im.getexif().get(274,1)!=1:raise ValueError('Unsupported image orientation/frame count')
        im.load()
        if im.mode not in ('RGB','RGBA','L'):raise ValueError('Unsupported crop mode; refuse pixel conversion')
        for r in (dataset.get('region_qc') or {}).get('regions',{}).get('source',[]):
            if r.get('comparison_type')!='GEOMETRY_DIAGRAM':continue
            box=r.get('bbox')
            if (not isinstance(box,list) or len(box)!=4 or any(type(x) is not int for x in box)
                    or not 0<=box[0]<box[2]<=im.width or not 0<=box[1]<box[3]<=im.height):
                rows.append({'region_id':r.get('id'),'status':'EVIDENCE_INCOMPLETE','reason':'Invalid or out-of-bounds source bbox'});continue
            target=root/f'geometry-{len(rows)+1}.png'
            with im.crop(box) as crop:
                with target.open('xb') as f:crop.save(f,format='PNG')
                with Image.open(target) as saved:
                    saved.load();exact=saved.mode==crop.mode and saved.size==crop.size and saved.tobytes()==crop.tobytes()
                if not exact:raise ValueError('Crop pixel preservation failed')
                rows.append({'region_id':r['id'],'bbox':box,'path':str(target.resolve()),'sha256':file_hash(target),
                             'decoded_pixels_exact':True,'status':'CANDIDATE_UNVERIFIED','eligible_for_final_page':False,
                             'source_sha256':expected,'predicted_geometry':True,
                             'note':'Region classification is not verification of diagram completeness, labels or incidence'})
    if file_hash(source)!=expected:raise ValueError('Source changed during extraction')
    return rows


def write_dataset(dataset,directory,*,export_crops=False):
    root=Path(directory);root.mkdir(parents=True)
    result=copy.deepcopy(dataset)
    if export_crops:
        try:result['geometry_crops']=export_geometry_crops(result,root/'geometry')
        except Exception as exc:
            result['crop_error']=type(exc).__name__+': '+str(exc)
            if result['readiness']['status']!='HIGH_RISK_HOLD':result['readiness']['status']='EVIDENCE_INCOMPLETE'
            result['readiness']['missing'].append('Source geometry extraction incomplete')
    result['readiness']=assess_readiness(result) if not result.get('crop_error') else result['readiness']
    # Inputs are immutable: publication consumers must check both hashes again.
    if any(file_hash(result[k]['path'])!=result[k]['sha256'] for k in ('source_image','translated_image')):
        raise ValueError('Input changed before dataset persistence')
    result.pop('dataset_sha256',None);result['dataset_sha256']=digest(result)
    with (root/'dataset.json').open('x',encoding='utf8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    return result
