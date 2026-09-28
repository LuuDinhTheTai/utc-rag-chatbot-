import Link from 'next/link';
import FreshmanGuide from '../../components/FreshmanGuide';
export default function FreshmenPage(){
  return <main className="admin-page"><header className="admin-header"><Link href="/" className="brand"><span className="logo">UTC</span><span>Tân sinh viên<small>ĐẠI HỌC GIAO THÔNG VẬN TẢI</small></span></Link><Link href="/">← Hỏi đáp tuyển sinh</Link><Link href="/majors">Ngành học</Link></header><FreshmanGuide/></main>;
}
