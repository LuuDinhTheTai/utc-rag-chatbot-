'use client';
import { useEffect, useState } from 'react';
import { api } from '../lib/api';

type Cutoff = {admission_year:number;campus:'hanoi'|'hcm';admission_code:string;program_name:string;method:'PT1'|'PT2'|'PT3'|'PT4';score:number;scale:number;source_url:string;note:string};
type Result = {items:Cutoff[];total:number;page:number;page_size:number};
type Options = {years:number[];methods:string[];majors:string[]};
const methodNames:Record<string,string>={PT1:'Điểm thi THPT',PT2:'Học bạ',PT3:'Đánh giá năng lực',PT4:'Đánh giá tư duy'};

export type CutoffSelection = {admission_code:string;program_name:string;campus:'hanoi'|'hcm'};
export default function CutoffLookup({selection,onClearSelection}:{selection?:CutoffSelection;onClearSelection?:()=>void}){
  const [major,setMajor]=useState('');
  const [year,setYear]=useState('');
  const [campus,setCampus]=useState(selection?.campus||'');
  const [method,setMethod]=useState('');
  const [page,setPage]=useState(1);
  const [options,setOptions]=useState<Options>({years:[],methods:[],majors:[]});
  const [result,setResult]=useState<Result>({items:[],total:0,page:1,page_size:25});
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  useEffect(()=>{let active=true;api<Partial<Options>>('/cutoffs/options').then(data=>{if(active)setOptions({years:Array.isArray(data?.years)?data.years:[],methods:Array.isArray(data?.methods)?data.methods:[],majors:Array.isArray(data?.majors)?data.majors:[]});}).catch(()=>{if(active)setOptions({years:[],methods:[],majors:[]});});return()=>{active=false;};},[]);
  useEffect(()=>{
    let active=true;setLoading(true);setError('');
    const params=new URLSearchParams({page:String(page),page_size:'25'});
    if(major)params.set('major',major);
    if(selection)params.set('admission_code',selection.admission_code);
    if(year)params.set('year',year);
    if(campus)params.set('campus',campus);
    if(method)params.set('method',method);
    api<Result>(`/cutoffs?${params}`).then(data=>{if(active)setResult(data);}).catch(e=>{if(active){setError(e.message);setResult({items:[],total:0,page,page_size:25});}}).finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[major,year,campus,method,page,selection]);
  const totalPages=Math.ceil(result.total/result.page_size);
  return <section className="cutoff-lookup">
    <div className="major-heading"><div><div className="eyebrow">DỮ LIỆU TUYỂN SINH CHÍNH THỨC</div><h1>Tra cứu điểm chuẩn các năm</h1><p className="muted">Xem điểm trúng tuyển theo ngành, cơ sở, phương thức và năm. Mỗi mức điểm có nguồn công bố của Trường Đại học Giao thông vận tải.</p></div></div>
    {selection&&<div className="selected-program"><div><strong>{selection.program_name}</strong><p>Mã xét tuyển {selection.admission_code} · {selection.campus==='hanoi'?'Hà Nội':'TP. Hồ Chí Minh'} · Điểm chuẩn các năm</p></div><button type="button" onClick={onClearSelection}>Xem tất cả ngành</button></div>}
    <div className="cutoff-filters panel" role="group" aria-label="Bộ lọc điểm chuẩn">
      {!selection&&<label>Ngành / chương trình<select value={major} onChange={e=>{setMajor(e.target.value);setPage(1);}}><option value="">Tất cả ngành</option>{options.majors.map(name=><option key={name} value={name}>{name}</option>)}</select></label>}
      <label>Năm<select value={year} onChange={e=>{setYear(e.target.value);setPage(1);}}><option value="">Tất cả năm</option>{options.years.map(y=><option key={y} value={y}>{y}</option>)}</select></label>
      <label>Cơ sở<select disabled={Boolean(selection)} value={campus} onChange={e=>{setCampus(e.target.value);setPage(1);}}><option value="">Tất cả cơ sở</option><option value="hanoi">Hà Nội</option><option value="hcm">TP. Hồ Chí Minh</option></select></label>
      <label>Phương thức<select value={method} onChange={e=>{setMethod(e.target.value);setPage(1);}}><option value="">Tất cả phương thức</option>{options.methods.map(m=><option key={m} value={m}>{m} · {methodNames[m]||m}</option>)}</select></label>
      <button type="button" disabled={!major&&!year&&(!campus||Boolean(selection))&&!method} onClick={()=>{setMajor('');setYear('');setCampus(selection?.campus||'');setMethod('');setPage(1);}}>Xóa bộ lọc</button>
    </div>
    <p className="cutoff-hint">Điểm được giữ nguyên theo thang công bố. PT3 ở Hà Nội và TP. Hồ Chí Minh dùng thang khác nhau; hãy xem cột “Điểm / thang” trước khi đối chiếu.</p>
    {error&&<div className="error" role="alert">{error}</div>}
    <div className="major-results" aria-live="polite">{loading?'Đang tải điểm chuẩn…':`${result.total} mức điểm phù hợp`}</div>
    {!loading&&!error&&result.items.length===0&&<div className="panel muted">Không có điểm chuẩn phù hợp. Hãy thử đổi ngành, cơ sở, phương thức hoặc năm.</div>}
    {result.items.length>0&&<div className="cutoff-table-wrap" tabIndex={0} aria-label="Bảng điểm chuẩn, có thể cuộn ngang trên màn hình nhỏ"><table className="cutoff-table"><thead><tr><th scope="col">Năm</th><th scope="col">Cơ sở</th><th scope="col">Mã xét tuyển</th><th scope="col">Ngành / chương trình</th><th scope="col">Phương thức</th><th scope="col">Điểm / thang</th><th scope="col">Tiêu chí phụ</th><th scope="col">Nguồn</th></tr></thead><tbody>{result.items.map(row=><tr key={`${row.admission_year}-${row.campus}-${row.admission_code}-${row.method}`}><td>{row.admission_year}</td><td>{row.campus==='hanoi'?'Hà Nội':'TP. HCM'}</td><td><strong>{row.admission_code}</strong></td><td>{row.program_name}</td><td>{row.method} · {methodNames[row.method]}</td><td><strong>{row.score.toLocaleString('vi-VN',{maximumFractionDigits:2})}</strong> / {row.scale}</td><td>{row.note||'—'}</td><td><a href={row.source_url} target="_blank" rel="noopener noreferrer">Thông báo UTC ↗</a></td></tr>)}</tbody></table></div>}
    {totalPages>1&&<div className="cutoff-pagination"><button type="button" disabled={page<=1||loading} onClick={()=>setPage(p=>p-1)}>← Trước</button><span>Trang {page} / {totalPages}</span><button type="button" disabled={page>=totalPages||loading} onClick={()=>setPage(p=>p+1)}>Sau →</button></div>}
  </section>;
}
