'use client';
import {FormEvent,useCallback,useEffect,useState} from 'react';
import Link from 'next/link';
import {api,ApiError} from '../lib/api';
import {useRouter} from 'next/navigation';
import {usePlanner} from './PlannerProvider';
import type {Calculation,Campus,PlannerView,ScoreRule} from '../lib/planner';
import {useAuth} from './AuthProvider';
import UtcLogo from './UtcLogo';
import type {Major} from './MajorCatalogue';
import ScoreRuleManager from './ScoreRuleManager';

type Cutoff={admission_year:number;method:string;score:number;scale:number;source_url:string;program_name:string};
type Preference={id:string;admission_year:number;campus:Campus;admission_code:string;program_name:string;source_url:string;position:number;method:string;subject_group:string;notes:string;estimated_score:number|null;score_scale:number;available:boolean;cutoffs:Cutoff[];updated_at:string};
type Task={id:string;admission_year:number;title:string;description:string;due_date:string|null;completed:boolean;source_url:string};
const campusNames={hanoi:'Hà Nội',hcm:'TP. Hồ Chí Minh'};
const methodNames={PT1:'PT1 · Thi THPT',PT2:'PT2 · Học bạ',PT3:'PT3 · Đánh giá năng lực',PT4:'PT4 · Đánh giá tư duy'};
const json=(body:unknown,method='POST'):RequestInit=>({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
const message=(e:unknown)=>e instanceof Error?e.message:'Không thể thực hiện thao tác.';
const score=(value:number|string)=>Number(value).toLocaleString('vi-VN',{maximumFractionDigits:2});

type PlannerProps={view:PlannerView;initialYear?:number;initialCampus?:Campus;initialOffering?:string};
const featureInfo={
  calculator:{title:'Tính điểm xét tuyển',description:'Tính điểm tham khảo và xem rõ điểm môn, ưu tiên, điểm cộng cùng công thức áp dụng.'},
  preferences:{title:'Nguyện vọng cá nhân',description:'Lưu ngành yêu thích, sắp xếp theo mong muốn và đối chiếu điểm chuẩn có nguồn.'},
  checklist:{title:'Checklist & lịch tuyển sinh',description:'Theo dõi việc cần chuẩn bị, ngày bạn đặt và tiến độ hoàn thành.'},
};
export default function Planner(props:PlannerProps){
  const {token}=useAuth();
  return <PlannerSession key={`${token||'guest'}:${props.view}:${props.initialYear??''}:${props.initialCampus??''}:${props.initialOffering??''}`} {...props}/>;
}
function PlannerSession({view,initialYear,initialCampus,initialOffering=''}:PlannerProps){
  const {user,loading}=useAuth();
  const planner=usePlanner();
  const router=useRouter();
  const signedIn=Boolean(user?.id);
  const [year,setYear]=useState(initialYear??planner.year),[campus,setCampus]=useState<Campus>(initialCampus??planner.campus);
  const {setScope,setCalculation}=planner;
  useEffect(()=>{setScope(year,campus);},[year,campus,setScope]);
  const calculation=planner.calculation?.year===year&&planner.calculation.campus===campus?planner.calculation:null;
  const info=featureInfo[view];
  return <main className="planner-page">
    <header className="admin-header"><Link className="brand" href="/"><UtcLogo/><span>{info.title}<small>ĐẠI HỌC GIAO THÔNG VẬN TẢI</small></span></Link><Link href="/majors">Tra cứu ngành học →</Link></header>
    <div className="planner-heading"><div className="eyebrow">ĐỒNG HÀNH CÙNG THÍ SINH</div><h1>{info.title}</h1><p>{info.description}</p></div>
    <div className="planner-scope"><label>Năm tuyển sinh<select aria-label="Năm tuyển sinh" value={year} onChange={e=>{setYear(Number(e.target.value));setCalculation(null);}}>{Array.from({length:101},(_,i)=>2100-i).map(y=><option key={y}>{y}</option>)}</select></label>{view!=='checklist'&&<label>Cơ sở tra cứu<select aria-label="Cơ sở tra cứu" value={campus} onChange={e=>{setCampus(e.target.value as Campus);setCalculation(null);}}><option value="hanoi">Hà Nội · GHA</option><option value="hcm">TP. Hồ Chí Minh · GSA</option></select></label>}{view==='preferences'&&<p>Nguyện vọng của bạn có thể gồm cả hai cơ sở trong cùng năm.</p>}</div>
    {view==='calculator'&&<section id="planner-calculator"><Calculator key={`${year}:${campus}`} year={year} campus={campus} result={calculation} onResult={setCalculation} onPreferences={()=>router.push(`/preferences?year=${year}&campus=${campus}`)}/></section>}
    {view==='preferences'&&<section id="planner-preferences">{loading?<p role="status">Đang kiểm tra tài khoản…</p>:signedIn?<Preferences key={year} year={year} campus={campus} calculation={calculation} initialOffering={initialOffering}/>:<SignIn title="Lưu danh sách nguyện vọng của riêng bạn"/>}</section>}
    {view==='checklist'&&<section id="planner-checklist">{loading?<p role="status">Đang kiểm tra tài khoản…</p>:signedIn?<Checklist key={year} year={year}/>:<SignIn title="Theo dõi công việc và lịch tuyển sinh"/>}</section>}
  </main>;
}

function SignIn({title}:{title:string}){
  return <div className="panel planner-empty"><h2>{title}</h2><p>Đăng nhập để lưu kế hoạch vào tài khoản và tiếp tục trên thiết bị khác. Bạn có thể tính điểm tham khảo ngay khi chưa đăng nhập.</p><Link className="planner-link-button" href="/account">Đăng nhập hoặc tạo tài khoản →</Link></div>;
}

function Calculator({year,campus,result,onResult,onPreferences}:{year:number;campus:Campus;result:Calculation|null;onResult:(r:Calculation|null)=>void;onPreferences:()=>void}){
  const {user}=useAuth();
  const [rules,setRules]=useState<ScoreRule[]>([]),[ruleId,setRuleId]=useState(result?.inputs?.rule_id||'');
  const [marks,setMarks]=useState(result?.inputs?.scores||['','','']),[priority,setPriority]=useState(result?.inputs?.priority||'0'),[bonus,setBonus]=useState(result?.inputs?.bonus||'0');
  const [busy,setBusy]=useState(false),[loading,setLoading]=useState(true),[error,setError]=useState(''),[revision,setRevision]=useState(0);
  const selected=rules.find(r=>r.id===ruleId);
  useEffect(()=>{let active=true;setLoading(true);api<ScoreRule[]>(`/score-rules?year=${year}&campus=${campus}`).then(data=>{if(active){setRules(data);if(result?.inputs?.rule_id&&!data.some(rule=>rule.id===result.inputs?.rule_id)){setRuleId('');onResult(null);}}}).catch(e=>{if(active)setError(message(e));}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[year,campus,revision]);
  function change(){onResult(null);setError('');}
  async function calculate(event:FormEvent){event.preventDefault();setBusy(true);setError('');onResult(null);try{const calculated=await api<Calculation>('/score-calculations',json({year,campus,rule_id:ruleId||null,scores:marks,priority,bonus}));onResult({...calculated,inputs:{scores:marks,priority,bonus,rule_id:ruleId}});}catch(e){setError(message(e));}finally{setBusy(false);}}
  return <>
    <div className="planner-grid"><form className="panel planner-form" onSubmit={calculate}><div className="eyebrow">ĐIỂM BA MÔN · THANG 30</div><h2>Tính điểm tham khảo</h2><p>Áp dụng cho điểm ba môn thi THPT. Chọn công thức phù hợp hoặc tự nhập điểm ưu tiên đã điều chỉnh để tính thử.</p>
      {error&&<div className="error" role="alert">{error}</div>}
      <fieldset disabled={busy||loading}><label>Công thức<select aria-label="Công thức tính điểm" value={ruleId} onChange={e=>{setRuleId(e.target.value);setMarks(['','','']);setPriority('0');setBonus('0');change();}}><option value="">Tự tính tổng ba môn · chưa đối chiếu quy chế</option>{rules.map(r=><option key={r.id} value={r.id}>{r.subject_group} · {r.title}</option>)}</select></label>
      {!loading&&!rules.length&&<p className="planner-hint">Chưa có công thức được quản trị viên đối chiếu cho {year} · {campusNames[campus]}. Chế độ tự tính chỉ thực hiện phép cộng, không xác nhận điểm xét tuyển chính thức.</p>}
      {selected&&<div className="planner-rule"><strong>{selected.subject_group} · {selected.title}</strong><p>{selected.scope_note}</p><p>Hệ số: {selected.weights.join(' : ')}. Điểm môn được chuẩn hóa về thang 30.</p><a href={selected.source_url} target="_blank" rel="noreferrer">Nguồn do quản trị viên đối chiếu ↗</a></div>}
      <div className="planner-three">{marks.map((mark,i)=><label key={i}>{selected?.subjects[i]||`Điểm môn ${i+1}`}<input required type="number" min="0" max="10" step="0.01" inputMode="decimal" value={mark} onChange={e=>{setMarks(current=>current.map((m,index)=>index===i?e.target.value:m));change();}}/></label>)}</div>
      <div className="form-grid"><label>{selected?.priority_mode==='taper_30'?'Mức ưu tiên gốc (trước giảm dần)':'Điểm ưu tiên đã điều chỉnh'}<input required type="number" min="0" max={selected?.priority_mode==='none'?0:selected?.priority_cap??5} step="0.01" value={priority} onChange={e=>{setPriority(e.target.value);change();}}/></label><label>Điểm cộng theo quy chế<input required type="number" min="0" max={selected?.bonus_cap??3} step="0.01" value={bonus} onChange={e=>{setBonus(e.target.value);change();}}/></label></div>
      <p className="planner-hint">Bạn tự xác định quyền hưởng ưu tiên và điểm cộng từ thông báo áp dụng. Công cụ không suy ra diện ưu tiên từ thông tin cá nhân.</p><button className="primary" disabled={busy||loading}>{busy?'Đang tính…':'Tính điểm'}</button></fieldset>
    </form><div className="panel planner-result" aria-live="polite">{result?<><div className="eyebrow">{result.mode==='manual'?'KẾT QUẢ TỰ TÍNH':'THEO CÔNG THỨC ĐÃ CHỌN'}</div><div className="planner-score">{score(result.total)}<span>/30</span></div><dl><div><dt>Điểm môn đã chuẩn hóa</dt><dd>{score(result.base)}</dd></div><div><dt>Ưu tiên áp dụng</dt><dd>+ {score(result.priority_applied)}</dd></div><div><dt>Điểm cộng</dt><dd>+ {score(result.bonus)}</dd></div></dl><p>{result.formula}</p>{result.rule?.priority_mode==='taper_30'&&<p>{result.priority_formula}</p>}<p className="planner-hint">{result.notice}</p><button type="button" onClick={onPreferences}>Dùng điểm cho nguyện vọng →</button></>:<><div className="eyebrow">TỪNG BƯỚC RÕ RÀNG</div><h2>Hiểu cách điểm được tính</h2><p>Kết quả sẽ tách riêng điểm môn, ưu tiên và điểm cộng, kèm công thức để bạn kiểm tra.</p><p className="planner-hint">Điểm chuẩn lịch sử là thông tin tham khảo; không dùng để khẳng định khả năng trúng tuyển.</p></>}</div></div>
    {user?.role==='admin'&&<ScoreRuleManager year={year} campus={campus} rules={rules} onChanged={()=>{setRevision(v=>v+1);setRuleId('');setMarks(['','','']);setPriority('0');setBonus('0');onResult(null);}}/>}
  </>;
}

function Preferences({year,campus,calculation,initialOffering}:{year:number;campus:Campus;calculation:Calculation|null;initialOffering:string}){
  const [data,setData]=useState<{items:Preference[];revision:number}>({items:[],revision:0}),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const [q,setQ]=useState(''),[search,setSearch]=useState(''),[majors,setMajors]=useState<Major[]>([]),[searching,setSearching]=useState(true),[searchError,setSearchError]=useState('');
  const load=useCallback(async()=>{setData(await api(`/planner/preferences?year=${year}`));},[year]);
  useEffect(()=>{let active=true;setLoading(true);api<{items:Preference[];revision:number}>(`/planner/preferences?year=${year}`).then(next=>{if(active)setData(next);}).catch(e=>{if(active)setError(message(e));}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[year]);
  useEffect(()=>{let active=true;setSearching(true);setSearchError('');const params=new URLSearchParams({year:String(year),campus,q:search,page_size:'8'});api<{items:Major[]}>(`/majors?${params}`).then(async next=>{if(initialOffering&&!search){try{const picked=await api<Major>('/majors/'+encodeURIComponent(initialOffering));if(picked.admission_year===year&&picked.campus===campus)next.items=[picked,...next.items.filter(m=>m.id!==picked.id)];}catch{/* Search remains usable if a shared program is unavailable. */}}if(active)setMajors(next.items);}).catch(e=>{if(active)setSearchError(message(e));}).finally(()=>{if(active)setSearching(false);});return()=>{active=false;};},[year,campus,search,initialOffering]);
  async function run(action:()=>Promise<unknown>,success:string){setBusy(true);setError('');setNotice('');try{await action();await load();setNotice(success);}catch(e){setError(message(e));if(e instanceof ApiError&&e.status===409){try{await load();}catch{}}}finally{setBusy(false);}}
  function move(index:number,offset:number){const ids=data.items.map(p=>p.id);[ids[index],ids[index+offset]]=[ids[index+offset],ids[index]];run(()=>api('/planner/preferences/reorder',json({year,revision:data.revision,ids})),'Đã lưu thứ tự nguyện vọng.');}
  return <div className="planner-preferences"><div className="planner-section-heading"><div><div className="eyebrow">DANH SÁCH CÁ NHÂN · {year}</div><h2>Nguyện vọng theo thứ tự của bạn</h2><p>Đây là bản kế hoạch riêng. Bạn vẫn cần đăng ký nguyện vọng trên hệ thống tuyển sinh chính thức.</p></div><button disabled={busy||loading} onClick={()=>run(load,'Đã tải danh sách mới nhất.')}>Tải lại</button></div>
    {error&&<div className="error" role="alert">{error}</div>}{notice&&<div className="notice" role="status">{notice}</div>}
    <form className="panel planner-search" onSubmit={e=>{e.preventDefault();setSearch(q);}}><label>Tìm ngành để thêm · {campusNames[campus]}<input value={q} maxLength={100} placeholder="Tên ngành hoặc mã xét tuyển" onChange={e=>setQ(e.target.value)}/></label><button disabled={searching}>Tìm ngành</button></form>
    {searchError&&<p className="error" role="alert">{searchError}</p>}
    <p className="planner-hint">Hiển thị tối đa 8 kết quả tìm kiếm. <Link href="/majors">Xem danh mục đầy đủ →</Link></p><div className="planner-candidates">{searching?<p role="status">Đang tìm ngành…</p>:majors.length?majors.map(m=>{const saved=data.items.some(p=>p.admission_code===m.admission_code&&p.campus===m.campus);return <div className="planner-candidate" key={m.id}><div><span>{m.admission_code} · {campusNames[m.campus]}</span><strong>{m.program_name}</strong></div><button disabled={saved||busy||loading} onClick={()=>run(()=>api('/planner/preferences',json({offering_id:m.id,revision:data.revision})),`Đã thêm ${m.admission_code}.`)}>{saved?'Đã lưu':'+ Thêm'}</button></div>;}):<p>Không tìm thấy chương trình phù hợp. <Link href="/majors">Xem danh mục đầy đủ →</Link></p>}</div>
    {loading?<p role="status">Đang tải nguyện vọng…</p>:data.items.length?<ol className="planner-preference-list">{data.items.map((item,index)=><li key={item.id}><div className="planner-preference-heading"><span className="planner-rank">{index+1}</span><div><h3>{item.program_name}</h3><p>{item.admission_code} · {campusNames[item.campus]} · {item.admission_year}</p>{!item.available&&<p className="planner-hint">Chương trình không còn hiển thị trong danh mục. Bản lưu của bạn vẫn được giữ.</p>}</div><div className="planner-order"><button disabled={busy||index===0} aria-label={`Đưa ${item.admission_code} lên trên`} onClick={()=>move(index,-1)}>↑</button><button disabled={busy||index===data.items.length-1} aria-label={`Đưa ${item.admission_code} xuống dưới`} onClick={()=>move(index,1)}>↓</button></div></div>
      <PreferenceEditor key={item.id+item.updated_at} item={item} calculation={calculation} busy={busy} save={values=>run(()=>api('/planner/preferences/'+item.id,json({...values,revision:data.revision},'PATCH')),'Đã lưu thông tin nguyện vọng.')}/>
      <details className="planner-history"><summary>Đối chiếu điểm chuẩn lịch sử ({item.cutoffs.length})</summary><p className="planner-hint">Mỗi dòng giữ tên chương trình, năm, phương thức và thang điểm của nguồn. Không so sánh trực tiếp các thang điểm hoặc suy ra khả năng trúng tuyển.</p>{item.cutoffs.length?<div className="planner-history-list">{item.cutoffs.map((c,i)=><div key={i}><strong>{c.admission_year} · {c.method} · {score(c.score)}/{c.scale}</strong><span>{c.program_name}</span><a href={c.source_url} target="_blank" rel="noreferrer">Thông báo nguồn ↗</a></div>)}</div>:<p>Chưa có điểm chuẩn tương ứng mã xét tuyển và cơ sở này.</p>}</details>
      <div className="planner-card-footer"><a href={item.source_url} target="_blank" rel="noreferrer">Nguồn chương trình ↗</a><button disabled={busy} onClick={()=>{if(window.confirm(`Bỏ ${item.admission_code} khỏi kế hoạch?`))run(()=>api(`/planner/preferences/${item.id}?revision=${data.revision}`,{method:'DELETE'}),'Đã bỏ nguyện vọng khỏi kế hoạch.');}}>Bỏ khỏi danh sách</button></div>
    </li>)}</ol>:<div className="panel planner-empty"><h3>Bắt đầu với ngành bạn quan tâm</h3><p>Tìm ngành ở trên rồi bấm “Thêm”. Bạn có thể lưu tối đa 50 nguyện vọng mỗi năm trong công cụ này.</p></div>}
  </div>;
}
function PreferenceEditor({item,calculation,busy,save}:{item:Preference;calculation:Calculation|null;busy:boolean;save:(values:Record<string,unknown>)=>void}){
  const [method,setMethod]=useState(item.method),[group,setGroup]=useState(item.subject_group),[notes,setNotes]=useState(item.notes),[estimate,setEstimate]=useState(item.estimated_score===null?'':String(item.estimated_score)),[scale,setScale]=useState(item.score_scale);
  const compatible=calculation&&calculation.year===item.admission_year&&calculation.campus===item.campus&&method==='PT1'&&scale===30;
  return <form className="planner-form planner-preference-editor" onSubmit={e=>{e.preventDefault();save({method,subject_group:group,notes,estimated_score:estimate===''?null:estimate,score_scale:scale});}}><fieldset disabled={busy}><div className="form-grid"><label>Phương thức dự kiến<select aria-label="Phương thức dự kiến" value={method} onChange={e=>{setMethod(e.target.value);setEstimate('');}}>{Object.entries(methodNames).map(([key,label])=><option value={key} key={key}>{label}</option>)}</select></label><label>Tổ hợp môn dự kiến<input value={group} maxLength={20} placeholder="Ví dụ: A00" onChange={e=>setGroup(e.target.value)}/></label><label>Điểm của bạn (tham khảo)<input type="number" min="0" max={scale} step="0.01" value={estimate} onChange={e=>setEstimate(e.target.value)}/></label><label>Thang điểm<select aria-label="Thang điểm" value={scale} onChange={e=>{setScale(Number(e.target.value));setEstimate('');}}>{[30,100,150,1200].map(s=><option key={s}>{s}</option>)}</select></label></div>
    {compatible&&<button type="button" onClick={()=>{setEstimate(calculation.total);if(calculation.rule)setGroup(calculation.rule.subject_group);}}>Điền điểm vừa tính: {score(calculation.total)}/30 {calculation.mode==='manual'?'(tự tính)':''}</button>}
    <label>Ghi chú cá nhân<textarea rows={2} maxLength={2000} value={notes} placeholder="Điều kiện cần kiểm tra, lý do yêu thích ngành…" onChange={e=>setNotes(e.target.value)}/></label><button className="primary">Lưu thông tin</button></fieldset></form>;
}

const blankTask={title:'',description:'',due_date:'',source_url:''};
function Checklist({year}:{year:number}){
  const [tasks,setTasks]=useState<Task[]>([]),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const [draft,setDraft]=useState(blankTask),[editing,setEditing]=useState<string|null>(null),[today,setToday]=useState('');
  const load=useCallback(async()=>{setTasks(await api<Task[]>(`/planner/checklist?year=${year}`));},[year]);
  useEffect(()=>{let active=true;api<Task[]>(`/planner/checklist?year=${year}`).then(data=>{if(active)setTasks(data);}).catch(e=>{if(active)setError(message(e));}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[year]);
  useEffect(()=>{const update=()=>{const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Ho_Chi_Minh',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());const part=(type:string)=>parts.find(p=>p.type===type)?.value;setToday(`${part('year')}-${part('month')}-${part('day')}`);};update();const timer=setInterval(update,60000);return()=>clearInterval(timer);},[]);
  async function run(action:()=>Promise<unknown>,success:string){setBusy(true);setError('');setNotice('');try{await action();await load();setNotice(success);}catch(e){setError(message(e));}finally{setBusy(false);}}
  async function toggleTask(task:Task,completed:boolean){
    setTasks(current=>current.map(t=>t.id===task.id?{...t,completed}:t));setBusy(true);setError('');setNotice('');
    try{await api('/planner/checklist/'+task.id,json({completed},'PATCH'));await load();setNotice('Đã cập nhật tiến độ.');}
    catch(e){setTasks(current=>current.map(t=>t.id===task.id?{...t,completed:task.completed}:t));setError(message(e));}
    finally{setBusy(false);}
  }
  function save(event:FormEvent){event.preventDefault();run(async()=>{const values={...draft,due_date:draft.due_date||null};await api('/planner/checklist'+(editing?'/'+editing:''),json(editing?values:{...values,admission_year:year},editing?'PATCH':'POST'));setDraft(blankTask);setEditing(null);},editing?'Đã cập nhật công việc.':'Đã thêm công việc.');}
  async function download(){setBusy(true);setError('');try{const result=await api<{filename:string;content:string;events:number}>(`/planner/calendar?year=${year}`);if(!result.events){setNotice('Chưa có công việc chưa hoàn thành được đặt ngày để xuất lịch.');return;}const url=URL.createObjectURL(new Blob([result.content],{type:'text/calendar;charset=utf-8'}));const link=document.createElement('a');link.href=url;link.download=result.filename;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);setNotice(`Đã xuất ${result.events} mốc cá nhân. Nhập file .ics vào ứng dụng lịch để đặt nhắc việc.`);}catch(e){setError(message(e));}finally{setBusy(false);}}
  const completed=tasks.filter(t=>t.completed).length;
  return <><div className="planner-section-heading"><div><div className="eyebrow">CHECKLIST CÁ NHÂN · {year}</div><h2>Chuẩn bị từng việc, theo dõi từng mốc</h2><p>Ngày do bạn tự đặt theo thông báo chính thức. Công cụ không tự xác nhận hạn tuyển sinh.</p></div><div className="row-actions"><button disabled={busy||loading} onClick={()=>run(()=>api('/planner/checklist/templates',json({year})),'Đã bổ sung checklist gợi ý; giữ nguyên các việc bạn đã chỉnh sửa.')}>Thêm checklist gợi ý</button><button disabled={busy||loading} onClick={download}>Xuất lịch .ics</button></div></div>
    {error&&<div className="error" role="alert">{error}</div>}{notice&&<div className="notice" role="status">{notice}</div>}
    <div className="panel planner-progress"><span>{completed}/{tasks.length} việc đã hoàn thành</span><progress aria-label="Tiến độ chuẩn bị tuyển sinh" value={completed} max={Math.max(tasks.length,1)}/></div>
    <div className="planner-grid"><form id="planner-task-editor" className="panel planner-form" onSubmit={save}><h3>{editing?'Chỉnh sửa công việc':'Thêm công việc của bạn'}</h3><fieldset disabled={busy}><label>Tên công việc<input required minLength={2} maxLength={200} value={draft.title} onChange={e=>setDraft(d=>({...d,title:e.target.value}))}/></label><label>Ngày dự kiến / hạn cần theo dõi<input type="date" min="2000-01-01" max="2100-12-31" value={draft.due_date} onChange={e=>setDraft(d=>({...d,due_date:e.target.value}))}/></label><label>Ghi chú<textarea rows={3} maxLength={2000} value={draft.description} onChange={e=>setDraft(d=>({...d,description:e.target.value}))}/></label><label>Liên kết thông báo bạn đối chiếu (không bắt buộc)<input type="url" pattern="https://.*" maxLength={2000} placeholder="https://…" value={draft.source_url} onChange={e=>setDraft(d=>({...d,source_url:e.target.value}))}/></label><div className="row-actions"><button className="primary">{editing?'Lưu chỉnh sửa':'Thêm công việc'}</button>{editing&&<button type="button" onClick={()=>{setEditing(null);setDraft(blankTask);}}>Hủy</button>}</div></fieldset></form>
    <div>{loading?<p role="status">Đang tải checklist…</p>:tasks.length?<ul className="planner-task-list">{tasks.map(task=>{const overdue=!task.completed&&task.due_date&&today&&task.due_date<today;return <li className={task.completed?'task-completed':''} key={task.id}><label className="planner-task-check"><input type="checkbox" checked={task.completed} disabled={busy} onChange={e=>toggleTask(task,e.target.checked)}/><strong>{task.title}</strong></label><p>{task.description}</p><div className="planner-task-meta"><span className={overdue?'planner-overdue':''}>{task.due_date?`${overdue?'Quá ngày bạn đặt · ':''}${task.due_date.split('-').reverse().join('/')}`:'Chưa đặt ngày'}</span>{task.source_url&&<a href={task.source_url} target="_blank" rel="noreferrer">Nguồn bạn đã lưu ↗</a>}</div><div className="row-actions"><button disabled={busy} onClick={()=>{setEditing(task.id);setDraft({title:task.title,description:task.description,due_date:task.due_date||'',source_url:task.source_url});document.getElementById('planner-task-editor')?.scrollIntoView({block:'center',behavior:'smooth'});}}>Sửa</button><button disabled={busy} onClick={()=>{if(window.confirm(`Xóa công việc “${task.title}”?`))run(async()=>{await api('/planner/checklist/'+task.id,{method:'DELETE'});if(editing===task.id){setEditing(null);setDraft(blankTask);}},'Đã xóa công việc.');}}>Xóa</button></div></li>;})}</ul>:<div className="panel planner-empty"><h3>Kế hoạch bắt đầu từ một việc nhỏ</h3><p>Thêm việc của bạn hoặc dùng checklist gợi ý. Các mục gợi ý chưa có ngày đến hạn.</p></div>}</div></div>
  </>;
}
