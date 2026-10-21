import Link from 'next/link';
import UtcLogo from '../../components/UtcLogo';
import AdmissionsExplorer from '../../components/AdmissionsExplorer';
export default async function MajorsPage({searchParams}:{searchParams:Promise<{view?:string}>}){
  const params=await searchParams;
  return <main className="admin-page admissions-explorer"><header className="admin-header"><Link href="/" className="brand"><UtcLogo/><span>Ngành học & điểm chuẩn<small>ĐẠI HỌC GIAO THÔNG VẬN TẢI</small></span></Link><Link href="/">← Hỏi đáp tuyển sinh</Link></header><AdmissionsExplorer initialView={params.view==='cutoffs'?'cutoffs':'majors'}/></main>;
}
