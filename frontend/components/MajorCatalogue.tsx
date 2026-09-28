'use client';
import { FormEvent, useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';

type Major = {
  id: string; admission_code: string; major_code: string; name: string; program_name: string;
  admission_year: number; campus: 'hanoi' | 'hcm'; quota: number | null;
  methods: string[]; subject_groups: string[]; notes: string; source_url: string; is_active: boolean;
};
type Draft = Omit<Major,'id'>;
type Result = {items: Major[]; total: number};
const blank: Draft = {admission_code:'',major_code:'',name:'',program_name:'',admission_year:2026,campus:'hanoi',quota:null,methods:[],subject_groups:[],notes:'',source_url:'https://tuyensinh.utc.edu.vn/',is_active:true};
const methodNames: Record<string,string> = {PT1:'Thi tốt nghiệp THPT / giải quốc gia, quốc tế',PT2:'Học bạ kết hợp điều kiện điểm thi',PT3:'Đánh giá năng lực',PT4:'Đánh giá tư duy'};

export default function MajorCatalogue({token}:{token?:string}) {
  const isAdmin=Boolean(token);
  const [result,setResult]=useState<Result>({items:[],total:0});
  const [query,setQuery]=useState(''),[search,setSearch]=useState(''),[year,setYear]=useState('2026'),[campus,setCampus]=useState('');
  const [page,setPage]=useState(1),[revision,setRevision]=useState(0),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false);
  const [error,setError]=useState(''),[notice,setNotice]=useState('');
  const [draft,setDraft]=useState<Draft|null>(null),[editing,setEditing]=useState<string|null>(null);
  const [methods,setMethods]=useState(''),[groups,setGroups]=useState('');
  const [jsonFile,setJsonFile]=useState<File>();
  const editor=useRef<HTMLFormElement>(null);
  const headers=token?{Authorization:`Bearer ${token}`}:undefined;
  useEffect(()=>{
    let active=true;setLoading(true);setError('');
    const params=new URLSearchParams({q:search,page:String(page),page_size:'12'});
    if(year)params.set('year',year);if(campus)params.set('campus',campus);
    api<Result>(`${token?'/admin':''}/majors?${params}`,{headers:token?{Authorization:`Bearer ${token}`}:undefined})
      .then(data=>{if(active)setResult(data);}).catch(e=>{if(active){setResult({items:[],total:0});setError(e.message);}})
      .finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[token,search,year,campus,page,revision]);
  async function run(action:()=>Promise<void>){
    setBusy(true);setError('');setNotice('');
    try{await action();}catch(e){setError(e instanceof Error?e.message:'Không thể thực hiện thao tác.');}finally{setBusy(false);}
  }
  function edit(item?:Major){
    setEditing(item?.id||null);
    const next:Draft=item?{admission_code:item.admission_code,major_code:item.major_code,name:item.name,program_name:item.program_name,admission_year:item.admission_year,campus:item.campus,quota:item.quota,methods:item.methods,subject_groups:item.subject_groups,notes:item.notes,source_url:item.source_url,is_active:item.is_active}:{...blank};
    setDraft(next);setMethods(next.methods.join('; '));setGroups(next.subject_groups.join(', '));
    setTimeout(()=>editor.current?.scrollIntoView({behavior:'smooth',block:'start'}),0);
  }
  function save(e:FormEvent){
    e.preventDefault();if(!draft)return;
    run(async()=>{
      const split=(s:string)=>s.split(/[,;\s]+/).filter(Boolean).map(v=>v.toUpperCase());
      await api(`/admin/majors${editing?'/'+editing:''}`,{method:editing?'PATCH':'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({...draft,admission_code:draft.admission_code.trim().toUpperCase(),major_code:draft.major_code.trim().toUpperCase(),methods:methods.split(/[;\n]+/).map(v=>v.trim()).filter(Boolean),subject_groups:split(groups)})});
      setNotice(editing?'Đã cập nhật ngành học.':'Đã thêm ngành học.');setDraft(null);setEditing(null);setRevision(v=>v+1);
    });
  }
  function remove(item:Major){
    if(!window.confirm(`Xóa chương trình ${item.admission_code} — ${item.program_name} (${item.admission_year})? Thao tác này xóa khỏi danh mục ngành học.`))return;
    run(async()=>{await api(`/admin/majors/${item.id}`,{method:'DELETE',headers});if(editing===item.id)setDraft(null);setNotice('Đã xóa ngành học.');setPage(1);setRevision(v=>v+1);});
  }
  function importFile(){
    if(!jsonFile)return;
    run(async()=>{const form=new FormData();form.append('file',jsonFile);const response=await api<{inserted:number;skipped:number}>('/admin/majors/import',{method:'POST',headers,body:form});setNotice(`Đã thêm ${response.inserted} chương trình; bỏ qua ${response.skipped} bản ghi đã tồn tại.`);setPage(1);setRevision(v=>v+1);});
  }
  function field<K extends keyof Draft>(key:K,value:Draft[K]){setDraft(d=>d?{...d,[key]:value}:d);}
  return <section className="major-catalogue">
    <div className="major-heading"><div><div className="eyebrow">{isAdmin?'QUẢN TRỊ DANH MỤC':'KHÁM PHÁ NGÀNH HỌC'}</div><h1>{isAdmin?'Quản lý ngành học':'Chọn ngành, mở tương lai'}</h1><p className="muted">Tra cứu theo chương trình, năm tuyển sinh và cơ sở đào tạo.</p></div>{isAdmin&&<button className="primary" disabled={busy} onClick={()=>edit()}>＋ Thêm ngành học</button>}</div>
    {error&&<div className="error" role="alert">{error}</div>}{notice&&<div className="notice" role="status">{notice}</div>}
    {isAdmin&&<details className="panel"><summary>Nhập ngành học từ JSON</summary><p className="muted">Chọn JSON có metadata và chi_tieu_YYYY → GHA/GSA → programs. Tối đa 2 MB. Bản ghi trùng năm, cơ sở và mã xét tuyển được bỏ qua.</p><input aria-label="Tệp JSON ngành học" type="file" accept=".json,application/json" onChange={e=>setJsonFile(e.target.files?.[0])}/><button disabled={busy||!jsonFile} onClick={importFile}>Nhập dữ liệu</button></details>}
    {isAdmin&&draft&&<form className="panel major-editor" ref={editor} onSubmit={save}><h2>{editing?'Chỉnh sửa chương trình':'Thêm chương trình tuyển sinh'}</h2><fieldset disabled={busy}><div className="form-grid">
      <label>Mã xét tuyển<input required minLength={2} maxLength={30} value={draft.admission_code} onChange={e=>field('admission_code',e.target.value)}/></label>
      <label>Mã ngành<input required minLength={3} maxLength={30} value={draft.major_code} onChange={e=>field('major_code',e.target.value)}/></label>
      <label>Tên ngành<input required minLength={2} maxLength={300} value={draft.name} onChange={e=>field('name',e.target.value)}/></label>
      <label>Tên chương trình / chuyên ngành<input required minLength={2} maxLength={500} value={draft.program_name} onChange={e=>field('program_name',e.target.value)}/></label>
      <label>Năm tuyển sinh<input type="number" required min={2000} max={2100} step={1} value={draft.admission_year} onChange={e=>field('admission_year',Number(e.target.value))}/></label>
      <label>Cơ sở<select value={draft.campus} onChange={e=>field('campus',e.target.value as Draft['campus'])}><option value="hanoi">Hà Nội · GHA</option><option value="hcm">TP. Hồ Chí Minh · GSA</option></select></label>
      <label>Chỉ tiêu dự kiến (để trống nếu chưa công bố)<input type="number" min={0} max={100000} step={1} value={draft.quota??''} onChange={e=>field('quota',e.target.value===''?null:Number(e.target.value))}/></label>
      <label>Phương thức (cách nhau bằng dấu chấm phẩy)<input value={methods} maxLength={10000} placeholder="PT1; PT2; PT3" onChange={e=>setMethods(e.target.value)}/></label>
      <label>Tổ hợp môn PT1 / PT2<input value={groups} maxLength={600} placeholder="A00, A01, D01" onChange={e=>setGroups(e.target.value)}/></label>
      <label>URL nguồn chính thức<input type="url" required maxLength={2000} value={draft.source_url} onChange={e=>field('source_url',e.target.value)}/></label>
    </div><label className="major-notes">Ghi chú / điều kiện riêng<textarea rows={4} maxLength={10000} value={draft.notes} onChange={e=>field('notes',e.target.value)}/></label>
    <label className="major-checkbox"><input type="checkbox" checked={draft.is_active} onChange={e=>field('is_active',e.target.checked)}/> Hiển thị cho người dùng</label>
    <div className="row-actions"><button className="primary" type="submit">Lưu ngành học</button><button type="button" onClick={()=>setDraft(null)}>Hủy</button></div></fieldset></form>}
    <form className="major-filters panel" onSubmit={e=>{e.preventDefault();setSearch(query);setPage(1);}}>
      <label>Tên ngành hoặc mã<input maxLength={100} placeholder="Công nghệ thông tin, GHA…" value={query} onChange={e=>setQuery(e.target.value)}/></label>
      <label>Năm tuyển sinh<input type="number" min={2000} max={2100} step={1} placeholder="Tất cả" value={year} onChange={e=>{setYear(e.target.value);setPage(1);}}/></label>
      <label>Cơ sở<select value={campus} onChange={e=>{setCampus(e.target.value);setPage(1);}}><option value="">Tất cả cơ sở</option><option value="hanoi">Hà Nội</option><option value="hcm">TP. Hồ Chí Minh</option></select></label><button type="submit">Tìm kiếm</button>
    </form>
    <div className="major-results" aria-live="polite">{loading?'Đang tải danh mục…':`${result.total} chương trình phù hợp`}</div>
    {!loading&&result.items.length===0&&<div className="panel muted">Không có ngành học phù hợp. Thử đổi từ khóa, năm hoặc cơ sở.</div>}
    {!loading&&result.items.length>0&&<div className="major-table-scroll" role="region" aria-label="Danh sách ngành học" tabIndex={0}>
      <table className="major-table">
        <caption className="sr-only">Danh sách chương trình tuyển sinh, trang {page}</caption>
        <thead><tr>
          <th scope="col">Mã xét tuyển</th>
          <th scope="col">Ngành / chương trình</th>
          <th scope="col">Mã ngành</th>
          <th scope="col">Năm</th>
          <th scope="col">Cơ sở</th>
          <th scope="col">Chỉ tiêu</th>
          <th scope="col">Tổ hợp</th>
          <th scope="col">Chi tiết</th>
          {isAdmin&&<th scope="col">Trạng thái / thao tác</th>}
        </tr></thead>
        <tbody>{result.items.map(item=><tr key={item.id}>
          <td className="major-table-code">{item.admission_code}</td>
          <td className="major-table-name"><strong>{item.name}</strong><span>{item.program_name}</span></td>
          <td>{item.major_code}</td>
          <td>{item.admission_year}</td>
          <td>{item.campus==='hanoi'?'Hà Nội':'TP. HCM'}</td>
          <td>{item.quota??'Chưa công bố'}</td>
          <td>{item.subject_groups.length?item.subject_groups.join(', '):'—'}</td>
          <td><details className="major-table-details"><summary>Xem</summary>
            <div><strong>Phương thức tuyển sinh</strong>{item.methods.length?<ul>{item.methods.map(m=><li key={m}>{methodNames[m]?m+': '+methodNames[m]:m}</li>)}</ul>:<p>Chưa công bố phương thức.</p>}
              <p className="major-note-text">{item.notes||'Chưa có ghi chú riêng trong dữ liệu.'}</p>
              <a href={item.source_url} target="_blank" rel="noreferrer">Xem thông báo nguồn ↗</a>
            </div>
          </details></td>
          {isAdmin&&<td className="major-table-actions"><span className={item.is_active?'status ready':'status'}>{item.is_active?'Hiển thị':'Đã ẩn'}</span><button disabled={busy} onClick={()=>edit(item)}>Sửa</button><button disabled={busy} onClick={()=>remove(item)}>Xóa</button></td>}
        </tr>)}</tbody>
      </table>
    </div>}
    <nav className="major-pagination" aria-label="Phân trang ngành học"><button disabled={loading||page===1} onClick={()=>setPage(v=>v-1)}>← Trước</button><span>Trang {page} / {Math.max(1,Math.ceil(result.total/12))}</span><button disabled={loading||page*12>=result.total} onClick={()=>setPage(v=>v+1)}>Sau →</button></nav>
    <p className="disclaimer">Chỉ tiêu là dự kiến theo dữ liệu nguồn. Đối chiếu thông báo chính thức của trường trước khi đăng ký.</p>
  </section>;
}
