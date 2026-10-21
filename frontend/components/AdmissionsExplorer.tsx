'use client';
import {useRef, useState} from 'react';
import MajorCatalogue, {Major} from './MajorCatalogue';
import CutoffLookup, {CutoffSelection} from './CutoffLookup';
import Icon from './Icon';

export default function AdmissionsExplorer({initialView='majors'}:{initialView?:'majors'|'cutoffs'}) {
  const [view,setView]=useState(initialView);
  const [selection,setSelection]=useState<CutoffSelection>();
  const [revision,setRevision]=useState(0);
  const heading=useRef<HTMLHeadingElement>(null);
  function openScores(major:Major){
    setSelection({admission_code:major.admission_code,program_name:major.program_name,campus:major.campus});
    setRevision(value=>value+1);
    setView('cutoffs');
    heading.current?.scrollIntoView({block:'start'});
    heading.current?.focus({preventScroll:true});
  }
  return <>
    <div className="explorer-heading"><div className="eyebrow">THÔNG TIN TUYỂN SINH UTC</div><h1 ref={heading} tabIndex={-1}>Ngành học & điểm chuẩn</h1><p className="muted">Khám phá chương trình, so sánh ngành học và đối chiếu điểm trúng tuyển các năm tại cùng một nơi.</p></div>
    <div className="explorer-switch" role="group" aria-label="Nội dung tra cứu">
      <button type="button" aria-pressed={view==='majors'} aria-controls="explorer-majors" onClick={()=>setView('majors')}><Icon name="book"/>Danh mục ngành học</button>
      <button type="button" aria-pressed={view==='cutoffs'} aria-controls="explorer-cutoffs" onClick={()=>setView('cutoffs')}><Icon name="chart"/>Điểm chuẩn các năm</button>
    </div>
    <div id="explorer-majors" hidden={view!=='majors'}><MajorCatalogue onViewCutoffs={openScores}/></div>
    <div id="explorer-cutoffs" hidden={view!=='cutoffs'}>
      {view==='cutoffs'&&<CutoffLookup key={revision} selection={selection} onClearSelection={()=>{setSelection(undefined);setRevision(value=>value+1);}}/>}
    </div>
  </>;
}
